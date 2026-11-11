"""DataFrame versions of :func:`CAPEnewsindex.build_index`.

``run_index`` and ``run_index_with_history`` wrap the building blocks in
:mod:`CAPEnewsindex.dictionary` and :mod:`CAPEnewsindex.index` into a single call:
load the dictionary, read the article archive straight into EPU counts
(via :func:`CAPEnewsindex.index.count_archive`: files are read in parallel across
CPU cores and only compact per-article results are kept, never the whole
scope's text), and compute the index. Anyone who needs read/dedupe/count as separate,
in-memory steps should call :func:`CAPEnewsindex.read_articles`,
:func:`CAPEnewsindex.dedup.dedupe`, and :func:`CAPEnewsindex.index.count` directly
instead -- these two exist only to remove the boilerplate around the
common case.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

from . import dictionary as _dictionary
from . import index as _index
from .index import History


def _log(verbose: bool, message: str) -> None:
    if verbose:
        print(message, file=sys.stderr)


def _load_dictionary(keywords, *, verbose: bool) -> _dictionary.Dictionary:
    """Your keywords: a .json/.xlsx/.csv/.txt file, a dict, or a loaded Dictionary."""
    if keywords is None:
        raise ValueError("keywords are required: pass your keyword file (.xlsx, .csv, .txt or .json) or a dict. "
                         "To start from a template: CAPEnewsindex.keywords_template('my_keywords.xlsx').")
    if isinstance(keywords, _dictionary.Dictionary):
        return keywords
    if isinstance(keywords, (str, Path)):
        path = Path(keywords)
        if not path.exists():
            raise FileNotFoundError(f"keyword file not found: {path}")
        _log(verbose, f"Loading keywords from {path} ...")
    return _dictionary.read(keywords)


def _read_and_count(
    root: str | Path,
    keywords,
    countries: list[str] | str | None,
    *,
    verbose: bool,
    start: str | None = None,
    end: str | None = None,
    windows: list[tuple[str, str]] | None = None,
    workers: int | None = None,
    cache: bool | str | Path | None = False,
) -> pd.DataFrame:
    kw = _load_dictionary(keywords, verbose=verbose)

    _log(verbose, f"Reading articles from {root} ...")
    progress = (lambda message: _log(True, f"  {message}")) if verbose else None
    started = time.perf_counter()
    counts = _index.count_archive(
        root, kw, countries=countries, progress=progress, start=start, end=end, windows=windows,
        workers=workers, cache=cache,
    )
    elapsed = time.perf_counter() - started
    _log(
        verbose,
        f"Counted {int(counts['all_articles'].sum()):,} articles "
        f"({int(counts['epu_articles'].sum()):,} EPU) across {counts['country'].nunique()} countr(y/ies) "
        f"in {elapsed:,.1f}s.",
    )
    return counts


def run_index(
    root: str | Path,
    keywords,
    start: str,
    end: str,
    *,
    countries: list[str] | str | None = None,
    verbose: bool = True,
    workers: int | None = None,
    cache: bool | str | Path | None = False,
) -> pd.DataFrame:
    """Read an article archive and compute a single-window EPU index in one call.

    ``root`` is the article archive directory (see :func:`CAPEnewsindex.read_articles`);
    ``keywords`` your keywords: a .xlsx/.csv/.txt/.json file or a dict (required).
    ``start``/``end`` are the inclusive ``"YYYY-MM"`` window: ``sigma``/``mu``
    are fit from it and used to score that same window -- this is the
    no-history variant (see :func:`CAPEnewsindex.index.compute_index`). Only
    this window's month folders are ever read -- no earlier archive
    history is streamed, scanned, or shown in progress output.

    ``countries`` restricts which country folders under ``root`` are read
    (a list, or ``"all"``/omitted for every folder -- see
    :func:`CAPEnewsindex.read_articles`). Progress is printed to stderr unless
    ``verbose=False``.

    ``workers`` is the number of CPU cores to read with (default: all of
    them; small jobs run in a single process). ``cache=True`` keeps each
    article file's results in a local SQLite cache (or pass a file path), so
    later runs over the same months only read new or changed files. See
    :func:`CAPEnewsindex.index.count_archive`.
    """
    counts = _read_and_count(
        root, keywords, countries, verbose=verbose, start=start, end=end,
        workers=workers, cache=cache,
    )
    _log(verbose, f"Computing index for {start}..{end} ...")
    result = _index.compute_index(counts, start, end)
    _log(verbose, f"Done: {len(result):,} country-month rows.")
    return result


def run_index_with_history(
    root: str | Path,
    keywords,
    windows: list[tuple[str, str]],
    *,
    history: History | None = None,
    history_start: str | None = None,
    history_end: str | None = None,
    countries: list[str] | str | None = None,
    verbose: bool = True,
    workers: int | None = None,
    cache: bool | str | Path | None = False,
) -> tuple[pd.DataFrame, History]:
    """Read an article archive and score it against a frozen history in one call.

    ``root`` and ``keywords`` are as in :func:`run_index`. Either pass
    an already-fitted ``history`` (e.g. from :meth:`CAPEnewsindex.index.History.load`)
    to reuse it, or pass ``history_start``/``history_end`` to fit a new one
    from this archive -- exactly one of the two must be given. ``windows`` is
    a list of inclusive ``(start, end)`` pairs scored against that history
    (see :func:`CAPEnewsindex.index.score_windows`); this is the with-history
    variant.

    ``countries``, ``verbose``, ``workers`` and ``cache`` are as in
    :func:`run_index`. With ``cache=True``, a monthly update that re-fits or
    re-checks the history window only reads the new month's files.

    Returns ``(result, history)`` so a freshly fit history can be saved
    with :meth:`CAPEnewsindex.index.History.save` for reuse in later runs.
    """
    if history is None and (history_start is None or history_end is None):
        raise ValueError(
            "pass either history, or both history_start and history_end, to fit one"
        )
    if history is not None and (history_start is not None or history_end is not None):
        raise ValueError("pass history on its own, not alongside history_start/history_end")

    # Only process months needed for scoring and history fitting.
    required_windows = list(windows)

    if history is None:
        required_windows.append((history_start, history_end))

    # Preserve the previous unrestricted-reading behavior when no
    # scoring windows are requested with an existing history.
    selected_windows = required_windows if required_windows else None

    counts = _read_and_count(
        root, keywords, countries, verbose=verbose, windows=selected_windows,
        workers=workers, cache=cache,
    )

    fitted_fresh = history is None
    if fitted_fresh:
        _log(verbose, f"Fitting history {history_start}..{history_end} ...")
        history = _index.fit_history(counts, history_start, history_end)
    else:
        _log(verbose, f"Using provided history ({history.start}..{history.end}).")

    _log(verbose, f"Scoring {len(windows)} window(s) against the history ...")
    result = _index.score_windows(counts, history, windows)
    _log(verbose, f"Done: {len(result):,} country-month rows.")

    return result, history
