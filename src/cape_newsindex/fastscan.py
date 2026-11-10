"""Fast, parallel archive scanning: the engine behind :func:`cape_newsindex.index.count_archive`.

Gives exactly the same counts as the pandas path
(``count(dedupe(batch))`` for every country-month batch from
:func:`cape_newsindex.articles.iter_country_month_batches`), but much faster:

* **Discovery** lists the archive with ``os.scandir`` in parallel threads
  (a large gain on network / Google Drive folders, where every listing waits
  on the network).
* **One task per article file**, run across CPU cores in worker processes
  (largest files first, so all cores stay busy). Small jobs run in-process,
  where starting processes would cost more than it saves.
* **No pandas in the hot loop.** A worker reads the file with the standard
  ``csv`` module, classifies every article with
  :class:`cape_newsindex.match.IndexMatcher`, and sends back only compact arrays:
  one EPU flag and one 64-bit deduplication-key hash per article. Article
  text never leaves the worker.
* **Deduplication** then runs in the parent on those hashes, batch by batch,
  with the same keep-first order as :func:`cape_newsindex.dedup.dedupe`.
* **Optional cache** (``cache=True`` or a path): per-file results are stored
  in SQLite keyed by file path, size, modification time, and a fingerprint
  of the country's keywords and this engine's settings, so a re-run only
  reads files that are new or changed -- e.g. a monthly update re-reading
  the history window costs almost nothing.

Files the fast reader cannot parse exactly like ``pandas.read_csv`` (rows
with more fields than the header, columns pandas would read as numbers) are
read with pandas instead, so results never depend on which reader ran.
Deduplication keys are compared as 64-bit BLAKE2b hashes; the chance of two
different keys colliding in a country-month is negligible (about 1 in 10^10
even with a million articles).
"""

from __future__ import annotations

import contextlib
import csv
import gzip
import hashlib
import html
import io
import json
import os
import re
import sqlite3
import sys
import time
from array import array
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ._version import __version__
from .dedup import canonical_url
from .dictionary import EPU_GROUPS
from .match import IndexMatcher, light_normalize, normalize

#: Bump when anything changes how a file's per-article results are computed.
ENGINE_VERSION = "1"

# pandas.read_csv's default missing-value strings (pandas._libs.parsers.STR_NA_VALUES).
_NA_VALUES = frozenset(
    {
        "", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND",
        "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null",
    }
)
_REQUIRED = ("site", "date", "title", "url", "text")
# A value pandas could parse as a number (int, float, inf/nan spellings, thousands-free).
_NUMBER = re.compile(r"\s*[-+]?(\d+\.?\d*([eE][-+]?\d+)?|\.\d+([eE][-+]?\d+)?|inf|infinity)\s*", re.I)
_WINDOWS = sys.platform == "win32"


def _set_csv_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def _subdirs(path: str) -> list[os.DirEntry]:
    try:
        with os.scandir(path) as it:
            return sorted((e for e in it if e.is_dir()), key=lambda e: e.name)
    except OSError:
        return []


def _is_article_file(name: str) -> bool:
    lower = name.lower() if _WINDOWS else name  # pathlib.glob is case-insensitive on Windows
    return lower.endswith(".csv") or lower.endswith(".csv.gz")


def _month_wanted(
    ym: str, start: str | None, end: str | None, windows: list[tuple[str, str]] | None
) -> bool:
    if start is not None and ym < start:
        return False
    if end is not None and ym > end:
        return False
    if windows is not None and not any(a <= ym <= b for a, b in windows):
        return False
    return True


def discover(
    root: str | Path,
    countries: list[str] | str | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
    windows: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str, str, int, int]]:
    """Every article file under ``root/<country>/<newspaper>/<year-month>/``.

    Same files and month filtering as
    :func:`cape_newsindex.articles.iter_country_month_batches`. Returns
    ``(country, folder_month, path, size, mtime_ns)`` tuples, ordered by
    country (in ``countries`` order), month, then path.
    """
    from .articles import _resolve_countries

    root = Path(root)
    selected = _resolve_countries(root, countries)

    def list_site(job: tuple[str, str]) -> list[tuple[str, str, str, int, int]]:
        country, site_path = job
        found = []
        for month in _subdirs(site_path):
            ym = month.name
            if not _month_wanted(ym, start, end, windows):
                continue
            try:
                with os.scandir(month.path) as it:
                    for f in it:
                        if _is_article_file(f.name) and f.is_file():
                            st = f.stat()
                            found.append((country, ym, f.path, int(st.st_size), int(st.st_mtime_ns)))
            except OSError:
                continue
        return found

    jobs = [(country, site.path) for country in selected for site in _subdirs(str(root / country))]
    order = {country: i for i, country in enumerate(selected)}
    files: list[tuple[str, str, str, int, int]] = []
    with ThreadPoolExecutor(max_workers=32) as pool:
        for chunk in pool.map(list_site, jobs):
            files.extend(chunk)
    files.sort(key=lambda t: (order[t[0]], t[1], Path(t[2])))
    return files


# ---------------------------------------------------------------------------
# Worker: one file -> compact per-article results
# ---------------------------------------------------------------------------
_W_MATCHERS: dict[str, IndexMatcher | None] = {}
_W_TERMS: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None] = {}
_W_ENCODING = "utf-8"
_W_DEDUPE = True


def _worker_init(terms: dict, encoding: str, dedupe: bool) -> None:
    global _W_TERMS, _W_MATCHERS, _W_ENCODING, _W_DEDUPE
    _set_csv_limit()
    _W_TERMS = terms
    _W_MATCHERS = {}
    _W_ENCODING = encoding
    _W_DEDUPE = dedupe


def _matcher(country: str) -> IndexMatcher | None:
    if country not in _W_MATCHERS:
        entry = _W_TERMS.get(country)
        _W_MATCHERS[country] = IndexMatcher(entry) if entry is not None else None
    return _W_MATCHERS[country]


def _hash64(key: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(key.encode("utf-8", "surrogatepass"), digest_size=8).digest(), "little"
    )


class _NeedsPandas(Exception):
    """The fast reader can't guarantee pandas-identical parsing for this file."""


def _rows_fast(path: str, encoding: str):
    """``(site, date, title, url, text)`` per row, missing values as ``None``,
    parsed exactly as ``pandas.read_csv`` would -- or :class:`_NeedsPandas`."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if path.lower().endswith(".gz"):
        raw = gzip.decompress(raw)
    text = raw.decode(encoding)
    del raw
    if text.startswith("\ufeff"):  # pandas drops a leading BOM
        text = text[1:]
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None)
    while header is not None and not header:  # pandas skips leading blank lines
        header = next(reader, None)
    if header is None:
        raise _NeedsPandas("empty file")
    missing = [col for col in _REQUIRED if col not in header]
    if missing:
        raise ValueError(f"{path}: missing column(s) {missing}")
    width = len(header)
    idx = [header.index(col) for col in _REQUIRED]
    rows = []
    for row in reader:
        n = len(row)
        if n == 0:
            continue  # blank line
        if n > width:
            raise _NeedsPandas("row longer than header")
        rows.append(tuple((row[i] if i < n else None) for i in idx))
    out = [tuple(None if (v is None or v in _NA_VALUES) else v for v in r) for r in rows]
    # pandas turns an all-numeric column into numbers ("2024" -> 2024, "1.50" -> 1.5);
    # nearly never happens for article columns, but hand those files to pandas.
    for j in range(5):
        values = [r[j] for r in out if r[j] is not None]
        if values and all(_NUMBER.fullmatch(v) for v in values):
            raise _NeedsPandas("numeric column")
    return out


def _rows_pandas(path: str, country: str, encoding: str):
    from .articles import _read_one  # imports pandas; only for unusual files

    frame = _read_one(Path(path), country, encoding)

    def clean(v):
        if v is None or (isinstance(v, float) and v != v):
            return None
        return v if isinstance(v, str) else str(v)

    return [
        tuple(clean(v) for v in r)
        for r in zip(frame["site"], frame["date"], frame["title"], frame["url"], frame["text"])
    ]


def _read_rows(path: str, country: str, encoding: str):
    """Rows of one file; kept as a module-level function so tests can watch which files are read."""
    try:
        try:
            return _rows_fast(path, encoding)
        except _NeedsPandas:
            return _rows_pandas(path, country, encoding)
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        if str(path) in str(exc):
            raise
        try:  # same exception type, with the file named so it can be found and fixed
            wrapped = type(exc)(f"{path}: {exc}")
        except Exception:  # noqa: BLE001 -- e.g. UnicodeDecodeError; keep it, add the file name
            if hasattr(exc, "add_note"):
                exc.add_note(f"while reading {path}")
            raise exc from None
        raise wrapped from exc


def _unescape(value: str | None) -> str | None:
    return html.unescape(value) if value is not None else None


def scan_file(task: tuple[str, str]) -> tuple:
    """Classify every article in one file.

    Returns ``(path, n, sites, site_codes, months, month_codes, flags, keys)``:
    distinct ``site`` values (``None`` = missing) and per-row codes into
    them, distinct ``year_month`` strings and per-row codes, one EPU flag
    byte per row, and one 64-bit dedup-key hash per row (empty if not
    deduplicating). Raises ``KeyError`` naming the country if it has no
    dictionary entry and the file has rows.
    """
    country, path = task
    rows = _read_rows(path, country, _W_ENCODING)
    matcher = _matcher(country) if rows else None
    if rows and matcher is None:
        raise KeyError(f"countries missing from dictionary: {[country]}")
    sites: dict = {}
    months: dict = {}
    site_codes = array("i")
    month_codes = array("i")
    flags = bytearray()
    keys = array("Q")
    dedupe = _W_DEDUPE
    for site, date, title, url, text in rows:
        title = _unescape(title)
        text = _unescape(text)
        site_codes.append(sites.setdefault(site, len(sites)))
        ym = date[:7] if date is not None else None  # None: missing date (see _missing_date_month)
        month_codes.append(months.setdefault(ym, len(months)))
        flags.append(1 if matcher(light_normalize(f"{title or ''} {text or ''}")) else 0)
        if dedupe:
            key = canonical_url(url)
            if key:
                keys.append(_hash64("u" + key))
            else:
                blob = normalize(title) + "\x1f" + normalize(text)
                keys.append(_hash64("t" + blob))
    return (
        path,
        len(rows),
        list(sites),
        site_codes.tobytes(),
        list(months),
        month_codes.tobytes(),
        bytes(flags),
        keys.tobytes(),
    )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def default_cache_path() -> Path:
    base = os.environ.get("CAPE_NEWSINDEX_CACHE_DIR") or (
        os.environ.get("LOCALAPPDATA") if _WINDOWS else os.environ.get("XDG_CACHE_HOME")
    )
    root = Path(base) if base else Path.home() / ".cache"
    if not os.environ.get("CAPE_NEWSINDEX_CACHE_DIR"):
        root = root / "cape_newsindex"
    return root / "scan_cache.sqlite"


def _country_fingerprint(entry, encoding: str, dedupe: bool) -> str:
    blob = json.dumps(
        [ENGINE_VERSION, __version__, encoding, dedupe, [list(c) for c in entry] if entry else None],
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


class _Cache:
    def __init__(self, path: Path | None):
        self.db = None
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(path))
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS files(path TEXT, fp TEXT, size INTEGER, mtime INTEGER, "
                "result BLOB, PRIMARY KEY(path, fp))"
            )
        except (OSError, sqlite3.Error) as exc:
            print(f"cape_newsindex: scan cache unavailable ({exc}); reading every file.", file=sys.stderr)
            self.db = None

    def get(self, files, fps) -> dict[str, tuple]:
        import pickle

        hits: dict[str, tuple] = {}
        if self.db is None:
            return hits
        wanted = {(f[2], fps[f[0]]): f for f in files}
        paths = list({f[2] for f in files})
        for i in range(0, len(paths), 900):
            chunk = paths[i : i + 900]
            q = f"SELECT path, fp, size, mtime, result FROM files WHERE path IN ({','.join('?' * len(chunk))})"
            for path, fp, size, mtime, blob in self.db.execute(q, chunk):
                f = wanted.get((path, fp))
                if f is not None and f[3] == size and f[4] == mtime:
                    hits[path] = pickle.loads(blob)
        return hits

    def put(self, items: list[tuple]) -> None:
        import pickle

        if self.db is None or not items:
            return
        try:
            self.db.executemany(
                "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?)",
                [(f[2], fp, f[3], f[4], pickle.dumps(res, protocol=4)) for f, fp, res in items],
            )
            self.db.commit()
        except sqlite3.Error as exc:
            print(f"cape_newsindex: scan cache write skipped ({exc}).", file=sys.stderr)

    def close(self) -> None:
        if self.db is not None:
            self.db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
#: Below this many files (or bytes), scanning runs in-process: starting
#: worker processes would take longer than the scan itself.
INPROCESS_MAX_FILES = 6
INPROCESS_MAX_BYTES = 8_000_000


def _missing_date_month() -> str | None:
    """What the pandas path files an article with no date under.

    ``read_articles`` derives ``year_month`` with ``date.astype(str)``: pandas
    < 3 turns a missing date into the string ``"nan"`` (counted under month
    ``"nan"``), pandas >= 3 keeps it missing (deduplicated, but never
    counted). Follow whichever pandas is installed, so both paths agree.
    """
    import numpy as np
    import pandas as pd

    value = pd.Series([np.nan], dtype=object).astype(str).iloc[0]
    return value[:7] if isinstance(value, str) else None


def _batch_counts(country: str, results: list[tuple], dedupe: bool, missing_month: str | None):
    """Dedupe one (country, folder-month) batch and count per (site, year_month).

    ``results`` are :func:`scan_file` outputs in file order. Mirrors
    ``count(dedupe(batch))``: duplicates are (year_month, key) pairs, the
    first occurrence is kept, rows with a missing ``site`` are not counted.
    """
    seen: set[tuple[int, int]] = set()
    counts: dict[tuple, list[int]] = {}
    n_read = n_kept = 0
    month_labels: set[str] = set()
    for _path, n, sites, site_b, months, month_b, flags, keys_b in results:
        if not n:
            continue
        n_read += n
        site_codes = array("i")
        site_codes.frombytes(site_b)
        month_codes = array("i")
        month_codes.frombytes(month_b)
        keys = array("Q")
        keys.frombytes(keys_b)
        month_labels.update("nan" if m is None else m for m in months)
        for r in range(n):
            ym = months[month_codes[r]]
            if dedupe:
                k = (ym, keys[r])
                if k in seen:
                    continue
                seen.add(k)
            n_kept += 1
            site = sites[site_codes[r]]
            if ym is None:
                ym = missing_month
            if site is None or ym is None:
                continue
            c = counts.get((site, ym))
            if c is None:
                c = counts[(site, ym)] = [0, 0]
            c[0] += flags[r]
            c[1] += 1
    return counts, n_read, n_kept, sorted(month_labels)


def count_archive_fast(
    root: str | Path,
    dictionary,
    *,
    countries: list[str] | str | None = None,
    encoding: str = "utf-8",
    dedupe: bool = True,
    progress: Callable[[str], None] | None = None,
    start: str | None = None,
    end: str | None = None,
    windows: list[tuple[str, str]] | None = None,
    workers: int | None = None,
    cache: bool | str | Path | None = None,
    skipped: list | None = None,
    by_folder: bool = False,
    file_progress: Callable[[dict], None] | None = None,
    groups: tuple[str, ...] = EPU_GROUPS,
):
    """See :func:`cape_newsindex.index.count_archive` (this is its fast engine).

    ``skipped``: if a list is given, a file that cannot be read is skipped
    (counted as empty) and recorded there as a dict with ``country``,
    ``year_month``, ``file`` and ``error``, instead of stopping the run.

    ``file_progress``, if given, is called after every file with a dict:
    ``files_done``, ``files_total``, ``bytes_done``, ``bytes_total``,
    ``articles``, ``from_cache`` and ``seconds`` -- for a live progress line.

    ``by_folder=True`` keeps a ``folder_month`` column (the month folder each
    count came from), so one scan can serve several windows -- see
    :func:`collapse_folders`.
    """
    import pandas as pd

    files = discover(root, countries, start=start, end=end, windows=windows)
    if not files:
        raise FileNotFoundError(f"no article files found under {root}")

    needed = sorted({f[0] for f in files})
    terms = {
        c: (
            tuple(tuple(dictionary[c].terms(g)) for g in groups)
            if c in dictionary
            else None
        )
        for c in needed
    }
    fps = {c: _country_fingerprint(terms[c], encoding, dedupe) for c in needed}

    cache_path = default_cache_path() if cache is True else (Path(cache) if cache else None)
    store = _Cache(cache_path)
    results = store.get(files, fps)
    todo = [f for f in files if f[2] not in results]

    # Batches finish in any order; report each one as soon as its last file is done.
    batch_files: dict[tuple[str, str], list[str]] = {}
    for f in files:
        batch_files.setdefault((f[0], f[1]), []).append(f[2])
    remaining = {b: len(p) for b, p in batch_files.items()}
    batch_of = {f[2]: (f[0], f[1]) for f in files}
    batch_counts: dict[tuple[str, str], dict] = {}
    missing_month = _missing_date_month()

    def finish(batch: tuple[str, str]) -> None:
        country, _ym = batch
        ordered = [results.pop(p) for p in batch_files[batch]]  # freed once counted
        counts, n_read, n_kept, labels = _batch_counts(country, ordered, dedupe, missing_month)
        if n_read and terms[country] is None:
            raise KeyError(f"countries missing from dictionary: {[country]}")
        batch_counts[batch] = counts
        if progress is not None:
            epu = sum(c[0] for c in counts.values())
            label = ",".join(labels) if labels else "?"
            progress(f"{country} {label}: {n_read:,} articles ({n_kept:,} after dedup), {epu:,} EPU")

    def done(path: str) -> None:
        b = batch_of[path]
        remaining[b] -= 1
        if remaining[b] == 0:
            finish(b)

    stats = {"files_done": 0, "files_total": len(files), "bytes_done": 0,
             "bytes_total": sum(f[3] for f in files), "articles": 0,
             "from_cache": len(results), "seconds": 0.0}
    t_start = time.perf_counter()
    size_of = {f[2]: f[3] for f in files}

    def tick(path: str, n_articles: int) -> None:
        stats["files_done"] += 1
        stats["bytes_done"] += size_of[path]
        stats["articles"] += n_articles
        stats["seconds"] = time.perf_counter() - t_start
        if file_progress is not None:
            file_progress(dict(stats))

    for path in list(results):
        tick(path, results[path][1])
        done(path)

    if todo:
        todo_bytes = sum(f[3] for f in todo)
        n_workers = workers if workers is not None else (os.cpu_count() or 1)
        n_workers = max(1, min(n_workers, len(todo), 61 if _WINDOWS else n_workers))  # Windows pool limit
        if workers is None and (len(todo) <= INPROCESS_MAX_FILES or todo_bytes <= INPROCESS_MAX_BYTES):
            n_workers = 1
        pending: list[tuple] = []

        def handle(res: tuple, f: tuple) -> None:
            if isinstance(res, BaseException):
                if skipped is None or isinstance(res, KeyError):
                    raise res
                skipped.append({"country": f[0], "year_month": f[1], "file": f[2],
                                "error": f"{type(res).__name__}: {res}"})
                results[f[2]] = (f[2], 0, [], b"", [], b"", b"", b"")
                tick(f[2], 0)
                done(f[2])
                return
            results[f[2]] = res
            tick(f[2], res[1])
            pending.append((f, fps[f[0]], res))
            if len(pending) >= 200:
                store.put(pending)
                pending.clear()
            done(f[2])

        task_of = {f[2]: f for f in todo}
        work = sorted(todo, key=lambda f: -f[3])  # largest first keeps every core busy
        try:
            if n_workers == 1:
                _worker_init(terms, encoding, dedupe)
                for f in work:
                    try:
                        res = scan_file((f[0], f[2]))
                    except Exception as exc:  # noqa: BLE001 -- handle() decides: skip or raise
                        res = exc
                    handle(res, f)
            else:
                _run_pool(work, terms, encoding, dedupe, n_workers, task_of, handle)
        finally:
            store.put(pending)
            store.close()
    else:
        store.close()

    rows = [
        (batch[0], site, ym, batch[1], e, n)
        for batch in batch_files
        for (site, ym), (e, n) in batch_counts.get(batch, {}).items()
    ]
    combined = pd.DataFrame(
        rows, columns=["country", "site", "year_month", "folder_month", "epu_articles", "all_articles"]
    )
    return combined if by_folder else collapse_folders(combined)


def collapse_folders(counts, windows: list[tuple[str, str]] | None = None):
    """Counts per country-site-month from a ``by_folder=True`` scan, using only
    month folders inside ``windows`` (all folders if ``None``) -- exactly what
    a scan restricted to those windows would have returned."""
    import pandas as pd

    combined = counts
    if windows is not None:
        keep = pd.Series(False, index=counts.index)
        for a, b in windows:
            keep |= (counts["folder_month"] >= a) & (counts["folder_month"] <= b)
        combined = counts[keep]
    combined = combined[["country", "site", "year_month", "epu_articles", "all_articles"]].copy()
    for col in ("country", "site", "year_month"):
        combined[col] = combined[col].astype(str)
    combined["epu_articles"] = combined["epu_articles"].astype("int64")
    combined["all_articles"] = combined["all_articles"].astype("int64")
    result = combined.groupby(["country", "site", "year_month"], as_index=False)[
        ["epu_articles", "all_articles"]
    ].sum()
    return result.sort_values(["country", "site", "year_month"]).reset_index(drop=True)


@contextlib.contextmanager
def _workers_skip_main_module():
    """Start worker processes without re-running the caller's script.

    With the "spawn" start method (the only one on Windows), every worker
    normally re-imports the ``__main__`` script, so a script calling
    ``run_index`` at top level without an ``if __name__ == "__main__":``
    guard would crash. The workers only need :mod:`cape_newsindex.fastscan`, so
    the main module's file/spec are hidden while the workers start.
    """
    main = sys.modules.get("__main__")
    if main is None:
        yield
        return
    had_file = "__file__" in main.__dict__
    saved_file = main.__dict__.get("__file__")
    had_spec = "__spec__" in main.__dict__
    saved_spec = main.__dict__.get("__spec__")
    main.__dict__.pop("__file__", None)
    main.__spec__ = None
    try:
        yield
    finally:
        if had_file:
            main.__file__ = saved_file
        if had_spec:
            main.__spec__ = saved_spec
        else:
            main.__dict__.pop("__spec__", None)


def _run_pool(work, terms, encoding, dedupe, n_workers, task_of, handle) -> None:
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from concurrent.futures.process import BrokenProcessPool

    ctx = multiprocessing.get_context("spawn")  # same behaviour on Windows, macOS, Linux
    needed = {f[0] for f in work}
    sub_terms = {c: v for c, v in terms.items() if c in needed}
    try:
        with _workers_skip_main_module(), ProcessPoolExecutor(
            max_workers=n_workers, mp_context=ctx, initializer=_worker_init,
            initargs=(sub_terms, encoding, dedupe),
        ) as pool:
            futures = {pool.submit(scan_file, (f[0], f[2])): f for f in work}
            for fut in as_completed(futures):
                exc = fut.exception()
                if isinstance(exc, BrokenProcessPool):
                    raise exc
                handle(exc if exc is not None else fut.result(), futures[fut])
    except BrokenProcessPool as exc:
        raise RuntimeError(
            "cape_newsindex: the parallel worker processes stopped unexpectedly (often: out of memory). "
            "Pass workers=1 to scan in a single process, or fewer workers."
        ) from exc
