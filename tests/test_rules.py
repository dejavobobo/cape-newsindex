"""rules="cape" (the CAPE EPU index's conventions, the default) and rules="legacy"."""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
import pytest

import CAPEnewsindex as ni
from CAPEnewsindex import _rules, aggregate, dedup


# --- duplicate keys ----------------------------------------------------------------------
@pytest.mark.parametrize("url,key", [
    ("https://www.Site.com/Path//a/", "site.com/path/a"),
    ("http://site.com/path/a?utm_source=x", "site.com/path/a"),          # query dropped: path names the article
    ("https://odemocratagb.com/?p=48834&utm_x=1", "odemocratagb.com/?p=48834"),   # query names the article
    ("https://x.com/index.php?id=5&fbclid=2&lang=fr", "x.com/index.php?id=5"),
    ("https://ex.com:8080/A?b=1", "ex.com/a"),
    ("", ""), ("not a url", ""), (None, ""),
])
def test_cape_link_key_is_the_cape_index_key(url, key):
    assert dedup.cape_canonical_url(url) == key


def test_cape_keys_link_then_text_and_never_for_empty_rows():
    assert dedup.article_key("https://www.a.com/x/", "T", "B") == "ua.com/x"
    assert dedup.article_key("", " Title ", " Body ") == "ttitle\nbody"
    assert dedup.article_key("", "", "") == ""                       # never a duplicate
    assert dedup.article_key("", "", "", rules="legacy") != ""        # legacy: empty rows collapse


def test_dedupe_cape_keeps_rows_without_link_or_text():
    frame = pd.DataFrame({
        "country": ["X"] * 5, "year_month": ["2024-01"] * 5,
        "url": ["https://www.a.com/1", "http://a.com/1/", "", "", ""],
        "title": ["t", "t", "", "", "same"], "text": ["b", "b", "", "", "text"],
    })
    assert len(dedup.dedupe(frame)) == 4                 # the two links are one article; empty rows stay
    assert len(dedup.dedupe(frame, rules="legacy")) == 4  # legacy: links differ (scheme), empty rows collapse


def test_bad_rules_word():
    with pytest.raises(ValueError, match="rules must be"):
        _rules.check("index")


# --- reading the archive ------------------------------------------------------------------
def _write(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("site,date,title,url,text\n" + "\n".join(rows))


@pytest.fixture
def small_archive(tmp_path):
    root = tmp_path / "archive"
    # Two newspapers carry the same story; the first one by name keeps it (as the CAPE index).
    _write(root / "Algeria" / "b paper" / "2024-01" / "articles_b_2024-01.csv.gz", [
        'Other name,2024-02-03,"Crise : l&rsquo;économie",https://www.b.dz/1,"incertitude politique budgétaire économie"',
        'b paper,2024-01-05,Story,https://shared.com/x,"économie"',
    ])
    _write(root / "Algeria" / "A paper" / "2024-01" / "articles_A_2024-01.csv.gz", [
        'A paper,2024-01-05,Story,http://shared.com/x/,"économie"',
        'A paper,2024-01-06,Other,https://a.dz/2,"texte"',
    ])
    return root


def test_cape_counts_by_folder_and_keeps_the_first_newspaper_by_name(small_archive):
    kw = {"Algeria": {"economic": ["économie"], "policy": ["politique", "budgétaire"], "uncertainty": ["incertitude"]}}
    cape = ni.index.count_archive(small_archive, ni.dictionary.read(kw), cache=False, workers=1)
    got = {(r.site, r.year_month): (r.epu_articles, r.all_articles) for r in cape.itertuples()}
    assert got == {("A paper", "2024-01"): (0, 2), ("b paper", "2024-01"): (1, 1)}
    pandas_engine = ni.index.count_archive(small_archive, ni.dictionary.read(kw), engine="pandas")
    pd.testing.assert_frame_equal(cape, pandas_engine)

    legacy = ni.index.count_archive(small_archive, ni.dictionary.read(kw), cache=False, workers=1, rules="legacy")
    assert set(legacy["site"]) == {"A paper", "b paper", "Other name"}   # site column, date month
    assert "2024-02" in set(legacy["year_month"])


# --- groups ------------------------------------------------------------------------------------
def _two_countries():
    months = ["2020-01", "2020-02", "2020-03", "2020-04"]
    index = pd.DataFrame({"country": ["X"] * 4 + ["Y"] * 3, "year_month": months + months[:3],
                          "EPU": [100, 120, 80, 100, 90, 110, 100]})       # Y has no index in 2020-04
    weights = pd.DataFrame({"country": ["X"] * 4 + ["Y"] * 4, "year_month": months * 2,
                            "gdp": [1.0] * 4 + [3.0] * 4})
    return index, weights


def test_missing_country_is_neutral_with_its_weight():
    index, weights = _two_countries()
    neutral = aggregate.aggregate(index, weights, history_start="2020-01", history_end="2020-03")
    drop = aggregate.aggregate(index, weights, history_start="2020-01", history_end="2020-03", missing="drop")
    zx = (100 - 100) / pd.Series([100, 120, 80]).std(ddof=0)
    april_neutral = neutral.set_index("year_month").loc["2020-04"]
    assert april_neutral["n_neutral"] == 1 and april_neutral["weight_covered"] == pytest.approx(4.0)
    assert april_neutral["z"] == pytest.approx(zx * 1 / 4)          # Y counts as z = 0 with weight 3
    assert drop.set_index("year_month").loc["2020-04", "z"] == pytest.approx(zx)
    with pytest.raises(ValueError, match="missing must be"):
        aggregate.aggregate(index, weights, missing="zero")


def test_freeze_weights_after_the_history():
    _, weights = _two_countries()
    weights.loc[weights["year_month"] == "2020-04", "gdp"] = 99.0
    frozen = aggregate.freeze_weights_after(weights, "2020-03").set_index(["country", "year_month"])["gdp"]
    assert frozen["X", "2020-04"] == 1.0 and frozen["Y", "2020-04"] == 3.0
    assert frozen["X", "2020-02"] == 1.0


# --- the one call ------------------------------------------------------------------------------
def test_build_index_prints_and_saves_the_rules(small_archive, tmp_path, capsys):
    kw = {"Algeria": {"economic": ["économie"], "policy": ["politique"], "uncertainty": ["incertitude"]}}
    result = ni.build_index(small_archive, kw, "Algeria", cache=False, output=tmp_path / "out", files="excel")
    assert "Rules: cape" in capsys.readouterr().out
    assert result.settings["rules"] == "cape"
    sheet = pd.read_excel(tmp_path / "out" / "epu_results.xlsx", sheet_name="settings")
    assert sheet.set_index("setting").loc["rules", "value"].startswith("cape")
    grouped = ni.build_index(small_archive, kw, "Algeria", cache=False, verbose=False,
                             gdp=pd.DataFrame({"Country": ["Algeria"], "Year": [2024], "GDP": [1.0]}),
                             groups={"North": ["Algeria"]})
    assert grouped._settings_table().set_index("setting").loc["group: North", "value"] == "Algeria"
    legacy = ni.build_index(small_archive, kw, "Algeria", cache=False, verbose=False, rules="legacy")
    assert legacy.settings["rules"] == "legacy"


def test_a_locked_file_is_saved_under_a_new_name(small_archive, tmp_path, monkeypatch, capsys):
    kw = {"Algeria": {"economic": ["économie"], "policy": ["politique"], "uncertainty": ["incertitude"]}}
    result = ni.build_index(small_archive, kw, "Algeria", cache=False, verbose=False)
    out = tmp_path / "out"
    out.mkdir()
    locked = out / "epu_results.xlsx"
    locked.write_bytes(b"")
    real_open = open

    def fake_open(file, mode="r", *args, **kwargs):   # Excel keeps the file locked on Windows
        if Path(file) == locked and ("a" in mode or "w" in mode):
            raise PermissionError(13, "Permission denied", str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    result.save(out, files="excel")
    assert (out / "epu_results (1).xlsx").exists()
    assert "is open in another program" in capsys.readouterr().out
