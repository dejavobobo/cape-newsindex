"""run_index / run_index_with_history: one-call orchestration."""

import datetime
import gzip
from pathlib import Path

import pandas as pd
import pytest

import CAPEnewsindex as ni
from CAPEnewsindex import dictionary as _dictionary_module

DATA_DICTIONARY = _dictionary_module.TEMPLATE_PATH


def _write(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "site,date,title,url,text\n" + "\n".join(rows)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(body)


def _build_archive(root: Path) -> None:
    for month, epu_count, plain_count in [("2020-01", 1, 3), ("2020-02", 2, 2), ("2020-03", 1, 3)]:
        rows = [
            f'The Punch,{month}-01,"Government fiscal policy and inflation create uncertainty",'
            f"https://example.com/nigeria/{month}/{i},body"
            for i in range(epu_count)
        ] + [
            f'The Punch,{month}-02,"Local football result {i}",https://example.com/nigeria/{month}/p{i},body'
            for i in range(plain_count)
        ]
        _write(root / "Nigeria" / "The Punch" / month / f"articles_The Punch_{month}.csv.gz", rows)

    for month, epu_count, plain_count in [("2020-01", 2, 2), ("2020-02", 1, 3), ("2020-03", 2, 2)]:
        rows = [
            f'Daily Nation,{month}-01,"Fiscal policy and inflation create unstable economy",'
            f"https://example.com/kenya/{month}/{i},body"
            for i in range(epu_count)
        ] + [
            f'Daily Nation,{month}-02,"Weather update {i}",https://example.com/kenya/{month}/p{i},body'
            for i in range(plain_count)
        ]
        _write(root / "Kenya" / "Daily Nation" / month / f"articles_Daily Nation_{month}.csv.gz", rows)


def test_run_index_computes_a_single_window_index(tmp_path, capsys):
    _build_archive(tmp_path / "archive")

    result = ni.run_index(tmp_path / "archive", DATA_DICTIONARY, "2020-01", "2020-03")

    assert set(result["country"]) <= {"Nigeria", "Kenya"}
    assert (result["EPU"] >= 0).all()
    assert capsys.readouterr().err  # progress printed by default


def test_run_index_verbose_false_is_silent(tmp_path, capsys):
    _build_archive(tmp_path / "archive")

    ni.run_index(tmp_path / "archive", DATA_DICTIONARY, "2020-01", "2020-03", verbose=False)

    assert capsys.readouterr().err == ""


def test_run_index_only_streams_the_requested_window_not_earlier_archive_history(tmp_path, capsys):
    archive = tmp_path / "archive"
    _build_archive(archive)
    # A month well outside the requested 2020-01..2020-03 window -- run_index
    # must never read it, or mention it in progress output.
    _write(
        archive / "Nigeria" / "The Punch" / "2015-06" / "articles_The Punch_2015-06.csv.gz",
        ['The Punch,2015-06-01,"Old fiscal policy uncertainty story",https://example.com/old,body'],
    )

    ni.run_index(archive, DATA_DICTIONARY, "2020-01", "2020-03")

    progress_output = capsys.readouterr().err
    assert "2015-06" not in progress_output


def test_run_index_countries_filters_the_archive(tmp_path):
    _build_archive(tmp_path / "archive")

    result = ni.run_index(
        tmp_path / "archive", DATA_DICTIONARY, "2020-01", "2020-03", countries=["Nigeria"], verbose=False
    )

    assert set(result["country"]) == {"Nigeria"}


def test_run_index_raises_a_clear_error_for_a_missing_dictionary(tmp_path):
    _build_archive(tmp_path / "archive")

    with pytest.raises(FileNotFoundError, match="no-such-file.json"):
        ni.run_index(
            tmp_path / "archive", tmp_path / "no-such-file.json", "2020-01", "2020-03", verbose=False
        )


def test_run_index_with_history_fits_and_scores_in_one_call(tmp_path):
    _build_archive(tmp_path / "archive")

    result, history = ni.run_index_with_history(
        tmp_path / "archive",
        DATA_DICTIONARY,
        windows=[("2020-03", "2020-03")],
        history_start="2020-01",
        history_end="2020-02",
        verbose=False,
    )

    assert history.start == "2020-01" and history.end == "2020-02"
    assert set(result["window"]) == {"2020-03:2020-03"}
    assert set(result["country"]) <= {"Nigeria", "Kenya"}


def test_run_index_with_history_accepts_an_already_fitted_history(tmp_path):
    archive = tmp_path / "archive"
    _build_archive(archive)
    kw = ni.dictionary.load(DATA_DICTIONARY)
    counts = ni.index.count(ni.dedup.dedupe(ni.read_articles(archive)), kw)
    fitted = ni.index.fit_history(counts, start="2020-01", end="2020-02")

    result, returned_history = ni.run_index_with_history(
        archive, DATA_DICTIONARY, windows=[("2020-03", "2020-03")], history=fitted, verbose=False
    )

    assert returned_history is fitted
    assert set(result["window"]) == {"2020-03:2020-03"}


def test_run_index_with_history_requires_a_history_or_a_window(tmp_path):
    _build_archive(tmp_path / "archive")

    with pytest.raises(ValueError, match="history"):
        ni.run_index_with_history(
            tmp_path / "archive", DATA_DICTIONARY, windows=[("2020-03", "2020-03")], verbose=False
        )


def test_run_index_with_history_rejects_conflicting_history_arguments(tmp_path):
    archive = tmp_path / "archive"
    _build_archive(archive)
    kw = ni.dictionary.load(DATA_DICTIONARY)
    counts = ni.index.count(ni.dedup.dedupe(ni.read_articles(archive)), kw)
    fitted = ni.index.fit_history(counts, start="2020-01", end="2020-02")

    with pytest.raises(ValueError, match="history_start"):
        ni.run_index_with_history(
            archive,
            DATA_DICTIONARY,
            windows=[("2020-03", "2020-03")],
            history=fitted,
            history_start="2020-01",
            verbose=False,
        )

def test_run_index_requires_keywords(tmp_path):
    _build_archive(tmp_path / "archive")
    with pytest.raises(ValueError, match="keywords are required"):
        ni.run_index(tmp_path / "archive", None, "2020-01", "2020-03", verbose=False)


def test_removed_shortcuts_are_gone():
    for name in ("quick_index", "index_all", "index_countries", "index_region", "index_since", "rerun",
                 "autosave", "AFRICA_REGIONS"):
        assert not hasattr(ni, name), name


@pytest.mark.parametrize("reuse_history", [False, True], ids=["fresh", "reused"])
def test_run_index_with_history_reads_only_required_months(
    tmp_path, monkeypatch, reuse_history
):
    """Check that history scoring skips irrelevant archive months."""
    archive = tmp_path / "archive"
    _build_archive(archive)

    # Add two months outside the history and scoring windows.
    for month in ("2015-06", "2024-06"):
        _write(
            archive / "Nigeria" / "The Punch" / month
            / f"articles_The Punch_{month}.csv.gz",
            [
                f'The Punch,{month}-01,"Old fiscal policy uncertainty story",'
                f'https://example.com/nigeria/{month}/old,body'
            ],
        )

    history = None
    if reuse_history:
        keywords = ni.dictionary.load(DATA_DICTIONARY)
        articles = ni.read_articles(archive)
        counts = ni.index.count(ni.dedup.dedupe(articles), keywords)
        history = ni.index.fit_history(
            counts, start="2020-01", end="2020-02"
        )

    # Record every monthly article file opened.
    import CAPEnewsindex.fastscan as scan_module

    opened_months = []
    original_read_rows = scan_module._read_rows

    def recording_read_rows(path, country, encoding):
        opened_months.append(Path(path).parent.name)
        return original_read_rows(path, country, encoding)

    monkeypatch.setattr(scan_module, "_read_rows", recording_read_rows)

    kwargs = (
        {"history": history}
        if reuse_history
        else {"history_start": "2020-01", "history_end": "2020-02"}
    )

    result, _ = ni.run_index_with_history(
        archive,
        DATA_DICTIONARY,
        windows=[("2020-03", "2020-03")],
        countries=["Nigeria"],
        verbose=False,
        **kwargs,
    )

    assert set(result["window"]) == {"2020-03:2020-03"}

    expected = (
        {"2020-03"}
        if reuse_history
        else {"2020-01", "2020-02", "2020-03"}
    )

    assert set(opened_months) == expected, (
        f"Opened {sorted(set(opened_months))}; "
        f"expected only {sorted(expected)}"
    )

@pytest.mark.parametrize("reuse_history", [False, True], ids=["fresh", "reused"])
def test_history_optimization_preserves_epu_values(tmp_path, monkeypatch, reuse_history):
    """Selective month reading must produce identical EPU results."""
    archive = tmp_path / "archive"
    _build_archive(archive)

    # Include irrelevant months and a gap between the required periods.
    for month in ("2015-06", "2022-06", "2024-06"):
        _write(
            archive / "Nigeria" / "The Punch" / month
            / f"articles_The Punch_{month}.csv.gz",
            [
                f'The Punch,{month}-01,"Government fiscal policy creates uncertainty",'
                f'https://example.com/nigeria/{month}/old,body'
            ],
        )

    import CAPEnewsindex.pipeline as pipeline

    original_read_and_count = pipeline._read_and_count

    # Simulate the original implementation by ignoring date windows.
    def unfiltered_read_and_count(root, dictionary_path, countries, **kwargs):
        kwargs.pop("windows", None)
        return original_read_and_count(
            root, dictionary_path, countries, **kwargs
        )

    kwargs = {
        "windows": [("2020-03", "2020-03")],
        "countries": ["Nigeria"],
        "verbose": False,
    }

    if reuse_history:
        keywords = ni.dictionary.load(DATA_DICTIONARY)
        counts = ni.index.count(
            ni.dedup.dedupe(ni.read_articles(archive)),
            keywords,
        )
        history = ni.index.fit_history(
            counts, start="2020-01", end="2020-02"
        )
        kwargs["history"] = history
    else:
        kwargs["history_start"] = "2020-01"
        kwargs["history_end"] = "2020-02"

    # Run the optimized implementation.
    optimized_result, optimized_history = ni.run_index_with_history(
        archive, DATA_DICTIONARY, **kwargs
    )

    # Run with the original, unrestricted archive-reading behavior.
    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_read_and_count", unfiltered_read_and_count)
        original_result, original_history = ni.run_index_with_history(
            archive, DATA_DICTIONARY, **kwargs
        )

    # Compare the actual EPU results.
    pd.testing.assert_frame_equal(
        optimized_result,
        original_result,
    )

    # Compare history parameters when fitting a fresh history.
    if not reuse_history:
        assert optimized_history.start == original_history.start
        assert optimized_history.end == original_history.end


def test_run_index_with_history_skips_months_between_windows(
    tmp_path, monkeypatch
):
    """Only history and scoring months should be opened."""
    archive = tmp_path / "archive"
    _build_archive(archive)

    # Add an irrelevant month between the requested periods.
    for month in ("2020-06", "2022-01", "2024-06"):
        _write(
            archive / "Nigeria" / "The Punch" / month
            / f"articles_The Punch_{month}.csv.gz",
            [
                f'The Punch,{month}-01,"Government fiscal policy uncertainty",'
                f'https://example.com/nigeria/{month}/article,body'
            ],
        )

    import CAPEnewsindex.fastscan as scan_module

    opened_months = []
    original_read_rows = scan_module._read_rows

    def recording_read_rows(path, country, encoding):
        opened_months.append(Path(path).parent.name)
        return original_read_rows(path, country, encoding)

    monkeypatch.setattr(scan_module, "_read_rows", recording_read_rows)

    result, _ = ni.run_index_with_history(
        archive,
        DATA_DICTIONARY,
        windows=[
            ("2020-03", "2020-03"),
            ("2024-06", "2024-06"),
        ],
        history_start="2020-01",
        history_end="2020-02",
        countries=["Nigeria"],
        verbose=False,
    )

    assert set(opened_months) == {
        "2020-01",
        "2020-02",
        "2020-03",
        "2024-06",
    }

    assert set(result["window"]) == {
        "2020-03:2020-03",
        "2024-06:2024-06",
    }

def test_run_index_with_history_empty_windows(tmp_path):
    """An empty scoring-window list should be handled consistently."""
    archive = tmp_path / "archive"
    _build_archive(archive)

    keywords = ni.dictionary.load(DATA_DICTIONARY)
    articles = ni.read_articles(archive)
    counts = ni.index.count(ni.dedup.dedupe(articles), keywords)

    history = ni.index.fit_history(
        counts, start="2020-01", end="2020-02"
    )

    result, returned_history = ni.run_index_with_history(
        archive,
        DATA_DICTIONARY,
        windows=[],
        history=history,
        countries=["Nigeria"],
        verbose=False,
    )

    assert result.empty
    assert returned_history is history