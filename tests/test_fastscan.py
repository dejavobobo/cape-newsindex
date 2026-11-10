"""The fast engine must give exactly the counts of the original pandas path."""

from __future__ import annotations

import csv
import gzip
import io
import random
from pathlib import Path

import pandas as pd
import pytest

import cape_newsindex as ni
from cape_newsindex import dictionary, fastscan, index
from cape_newsindex.match import (
    ComponentMatcher,
    EPUMatcher,
    TokenComponentMatcher,
    component_pattern,
    light_normalize,
    normalize,
    word_tokens,
)

DATA_DICTIONARY = dictionary.DEFAULT_PATH
KW = dictionary.load(DATA_DICTIONARY)
FILL = "the of and to said government market city le la de et les في من على الحكومة".split()
COUNTRIES = ["Nigeria", "Morocco", "Egypt", "Ivory Coast"]


def _article(rng: random.Random, country: str) -> str:
    entry = KW[country]
    words = [rng.choice(FILL) for _ in range(rng.randint(3, 60))]
    for terms, p in ((entry.economic, 0.6), (entry.policy, 0.5), (entry.uncertainty, 0.4)):
        if terms and rng.random() < p:
            t = rng.choice(terms)
            t = rng.choice([t, t.upper(), t.replace(" ", "\n"), t.replace(" ", "-"), t + "s", "x" + t])
            words.insert(rng.randrange(len(words) + 1), t)
    text = " ".join(words)
    if rng.random() < 0.1:
        text += " &amp; &#8217;s"
    return text


def _build_messy_archive(root: Path, seed: int) -> None:
    """Duplicates (within and across newspapers), missing URLs/dates/sites,
    'NA' strings, BOMs, HTML entities, non-ASCII text, short rows, blank
    lines, reordered/extra columns, two files in one month, gz and plain."""
    rng = random.Random(seed)
    cols = ["site", "date", "title", "url", "text"]
    for country in COUNTRIES:
        for s in range(rng.randint(1, 3)):
            site = f"Site{s}"
            for m in range(1, rng.randint(2, 5)):
                ym = f"2024-{m:02d}"
                rows, pool = [], []
                for i in range(rng.randint(0, 30)):
                    url = rng.choice([
                        f"https://www.{site}.com/{ym}/{i}", f"https://{site}.com/{ym}/{i}/?utm_source=x",
                        "", "NA", f"https://other.com/shared/{rng.randint(0, 10)}",
                    ])
                    title = rng.choice(["Economy policy news", "NA", "", "Crise économique", "أزمة الاقتصاد", f"S{i}"])
                    date = rng.choice([f"{ym}-{rng.randint(1, 28):02d}", f"2024-{m + 1:02d}-01", ""])
                    site_value = rng.choice([site] * 8 + ["", "NA"])
                    row = [site_value, date, title, url, _article(rng, country)]
                    if pool and rng.random() < 0.25:
                        row = list(rng.choice(pool))
                        row[0] = site_value
                    pool.append(row)
                    rows.append(row)
                order = cols if rng.random() < 0.7 else rng.sample(cols, 5) + ["extra"]
                buf = io.StringIO()
                writer = csv.writer(buf, lineterminator=rng.choice(["\n", "\r\n"]))
                writer.writerow(order)
                for row in rows:
                    values = dict(zip(cols, row), extra="z")
                    out = [values[k] for k in order]
                    if rng.random() < 0.03:
                        out = out[:-1]
                    writer.writerow(out)
                    if rng.random() < 0.03:
                        buf.write("\n")
                data = ("﻿" if rng.random() < 0.1 else "") + buf.getvalue()
                folder = root / country / site / ym
                folder.mkdir(parents=True, exist_ok=True)
                name = f"articles_{site}_{ym}"
                if rng.random() < 0.6:
                    (folder / f"{name}.csv.gz").write_bytes(gzip.compress(data.encode()))
                else:
                    (folder / f"{name}.csv").write_text(data, encoding="utf-8", newline="")
                if rng.random() < 0.08:
                    (folder / f"{name}_part2.csv").write_text(data, encoding="utf-8", newline="")


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize(
    "options",
    [{}, {"dedupe": False}, {"start": "2024-02", "end": "2024-03"}, {"windows": [("2024-01", "2024-01"), ("2024-03", "2024-04")]}],
    ids=["all", "no-dedupe", "start-end", "windows"],
)
def test_fast_engine_matches_pandas_engine(tmp_path, seed, options):
    _build_messy_archive(tmp_path, seed)
    reference = index.count_archive(tmp_path, KW, engine="pandas", **options)
    fast = index.count_archive(tmp_path, KW, engine="fast", workers=1, **options)
    pd.testing.assert_frame_equal(fast, reference)


def test_fast_engine_matches_with_worker_processes_and_cache(tmp_path):
    archive = tmp_path / "archive"
    _build_messy_archive(archive, 99)
    cache = tmp_path / "cache.sqlite"
    reference = index.count_archive(archive, KW, engine="pandas")
    parallel = index.count_archive(archive, KW, workers=2, cache=cache)
    cached = index.count_archive(archive, KW, workers=2, cache=cache)
    pd.testing.assert_frame_equal(parallel, reference)
    pd.testing.assert_frame_equal(cached, reference)


def test_cache_rereads_only_new_or_changed_files(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    _build_messy_archive(archive, 3)
    cache = tmp_path / "cache.sqlite"
    index.count_archive(archive, KW, workers=1, cache=cache)

    read: list[str] = []
    original = fastscan._read_rows

    def recording(path, country, encoding):
        read.append(path)
        return original(path, country, encoding)

    monkeypatch.setattr(fastscan, "_read_rows", recording)
    index.count_archive(archive, KW, workers=1, cache=cache)
    assert read == []

    changed = sorted(archive.rglob("*.csv*"))[0]
    changed.write_bytes(changed.read_bytes() + (b"" if changed.suffix == ".gz" else b"\n"))
    import os, time

    os.utime(changed, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))
    result = index.count_archive(archive, KW, workers=1, cache=cache)
    assert read == [str(changed)]
    pd.testing.assert_frame_equal(result, index.count_archive(archive, KW, engine="pandas"))


def test_run_index_and_history_results_do_not_depend_on_the_engine(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    _build_messy_archive(archive, 7)
    fast = ni.run_index(archive, DATA_DICTIONARY, "2024-01", "2024-04", verbose=False, workers=1)
    fast_b, base_b = ni.run_index_with_history(
        archive, DATA_DICTIONARY, windows=[("2024-03", "2024-04")],
        history_start="2024-01", history_end="2024-02", verbose=False, workers=1,
    )
    original = index.count_archive

    def pandas_engine(*args, **kwargs):
        kwargs.pop("workers", None)
        kwargs.pop("cache", None)
        return original(*args, engine="pandas", **kwargs)

    monkeypatch.setattr(index, "count_archive", pandas_engine)
    slow = ni.run_index(archive, DATA_DICTIONARY, "2024-01", "2024-04", verbose=False)
    slow_b, _ = ni.run_index_with_history(
        archive, DATA_DICTIONARY, windows=[("2024-03", "2024-04")],
        history_start="2024-01", history_end="2024-02", verbose=False,
    )
    pd.testing.assert_frame_equal(fast, slow)
    pd.testing.assert_frame_equal(fast_b, slow_b)


def test_missing_dictionary_country_raises_keyerror(tmp_path):
    folder = tmp_path / "Atlantis" / "Paper" / "2024-01"
    folder.mkdir(parents=True)
    (folder / "a.csv").write_text("site,date,title,url,text\nPaper,2024-01-01,t,https://x.com/1,b\n")
    with pytest.raises(KeyError, match="Atlantis"):
        index.count_archive(tmp_path, KW, workers=1)


def test_unparseable_file_error_names_the_file(tmp_path):
    folder = tmp_path / "Nigeria" / "Paper" / "2024-01"
    folder.mkdir(parents=True)
    bad = folder / "a.csv"
    bad.write_text("site,date,title,url,text\na,b,c,d,e\n1,2,3,4,5,6\n7,8,9,10,11,12\n")
    with pytest.raises(Exception, match="a.csv"):
        index.count_archive(tmp_path, KW, workers=1)


def test_fast_matchers_agree_with_the_reference_pattern():
    rng = random.Random(0)
    noise = ["the", "_x", "x_", "1", "a-b", "l'", "’", "`", "—", "(", "«", "،", "-", " ", "\n", " ", "ﬁ", "é", "é"]
    for country, entry in KW.countries.items():
        lists = [entry.economic, entry.policy, entry.uncertainty, entry.trade]
        simple = [ComponentMatcher(t) for t in lists]
        token = [TokenComponentMatcher(t) for t in lists]
        reference = [component_pattern(t) for t in lists]
        epu = EPUMatcher(entry.economic, entry.policy, entry.uncertainty)
        terms = [t for lst in lists for t in lst]
        for _ in range(40):
            parts = []
            for _ in range(rng.randint(1, 20)):
                t = rng.choice(terms)
                parts.append(rng.choice([t, t[1:], t[:-1], t + "s", t.upper(), t.replace(" ", "-"), rng.choice(noise)]))
            raw = rng.choice([" ", "", "-", "\n"]).join(parts)
            ref_text, fast_text = normalize(raw), light_normalize(raw)
            tokens = word_tokens(fast_text)
            expected = [bool(p.search(ref_text)) for p in reference]
            assert [m(fast_text) for m in simple] == expected, (country, raw)
            assert [m(fast_text, tokens) for m in token] == expected, (country, raw)
            assert epu(fast_text) == (expected[0] and expected[1] and expected[2]), (country, raw)
