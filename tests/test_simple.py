"""ni.build_index: the one-call API gives the same numbers as the lower-level functions."""

from __future__ import annotations

from pathlib import Path

import pytest

import newsindex as ni
from test_fastscan import _build_messy_archive

KEYWORDS = ni.dictionary.DEFAULT_PATH
GDP = Path(__file__).resolve().parent / "data" / "gdp_ppp_2015_2025.csv"
TWO = ["Nigeria", "Morocco"]


@pytest.fixture
def archive(tmp_path):
    _build_messy_archive(tmp_path / "archive", 11)
    return tmp_path / "archive"


def test_two_countries_no_history_matches_run_index(archive):
    result = ni.build_index(archive, KEYWORDS, ["nigeria", "MOROCCO"], "2024-01", "2024-04", verbose=False, cache=False)
    expected = ni.run_index(archive, None, "2024-01", "2024-04", countries=TWO, verbose=False)
    assert result.country.reset_index(drop=True).equals(expected.reset_index(drop=True))
    assert set(result.wide.columns) <= set(TWO)


def test_two_countries_with_history_matches_run_index_with_history(archive):
    result = ni.build_index(archive, KEYWORDS, TWO, "2024-03", "2024-04", history=("2024-01", "2024-02"),
                            verbose=False, cache=False)
    expected, _ = ni.run_index_with_history(archive, None, windows=[("2024-03", "2024-04")],
                                             history_start="2024-01", history_end="2024-02",
                                             countries=TWO, verbose=False)
    assert result.country.reset_index(drop=True).equals(expected.drop(columns="window").reset_index(drop=True))
    assert result.history is not None


def test_one_country_as_plain_text(archive):
    result = ni.build_index(archive, KEYWORDS, "Nigeria", "2024-01", "2024-04", verbose=False, cache=False)
    assert set(result.country["country"]) <= {"Nigeria"}


def test_gdp_alone_gives_one_group_of_all_countries(archive):
    result = ni.build_index(archive, KEYWORDS, ["Nigeria", "Morocco", "Egypt"], "2024-01", "2024-04", gdp=GDP,
                            verbose=False, cache=False)
    assert set(result.groups["group"]) == {"All countries"}


def test_africa_preset(archive):
    result = ni.build_index(archive, KEYWORDS, ["Nigeria", "Morocco", "Egypt"], "2024-01", "2024-04", gdp=GDP,
                            groups="africa", verbose=False, cache=False)
    assert set(result.groups["group"]) <= {"West", "North", "Africa"} and "Africa" in set(result.groups["group"])


def test_groups_without_gdp_are_skipped(archive, capsys):
    result = ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", groups={"A": TWO}, cache=False)
    assert result.groups is None
    assert "group index is skipped" in capsys.readouterr().out


def test_empty_settings_are_skipped(archive):
    result = ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", history=None, gdp="", groups={},
                            output="", verbose=False, cache=False)
    expected = ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", verbose=False, cache=False)
    assert result.country.equals(expected.country)
    assert result.history is None and result.groups is None


def test_group_countries_without_gdp_or_not_in_run_are_named(archive, capsys):
    gdp = __import__("pandas").read_csv(GDP)
    gdp = gdp[gdp["Country"] != "Morocco"]
    result = ni.build_index(archive, KEYWORDS, ["Nigeria", "Morocco", "Egypt"], "2024-01", "2024-04", gdp=gdp,
                            groups={"Mix": ["Nigeria", "Morocco", "Egypt", "France"]}, cache=False)
    out = capsys.readouterr().out
    assert "no GDP for Morocco" in out and "France" in out
    assert set(result.groups["group"]) == {"Mix"}


def test_saved_history_can_be_reused(archive, tmp_path):
    first = ni.build_index(archive, KEYWORDS, TWO, "2024-03", "2024-04", history=("2024-01", "2024-02"),
                           verbose=False, cache=False)
    first.history.save(tmp_path / "history.json")
    again = ni.build_index(archive, KEYWORDS, TWO, "2024-03", "2024-04", history=tmp_path / "history.json",
                           verbose=False, cache=False)
    expected, _ = ni.run_index_with_history(archive, None, windows=[("2024-03", "2024-04")],
                                             history=ni.index.History.load(tmp_path / "history.json"),
                                             countries=TWO, verbose=False)
    assert again.country.reset_index(drop=True).equals(expected.drop(columns="window").reset_index(drop=True))


def test_show_and_save(archive, tmp_path, capsys):
    result = ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", verbose=False, cache=False)
    result.show()
    out = result.save(tmp_path / "out")
    assert "EPU index" in capsys.readouterr().out
    assert sorted(f.name for f in out.iterdir()) == ["epu_dashboard.html", "epu_results.xlsx"]


def test_broken_file_is_skipped_and_listed(archive):
    bad = sorted((archive / "Nigeria").rglob("*.csv*"))[0]
    bad.write_bytes(b"\xff\xfe not a csv \x00")
    result = ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", verbose=False, cache=False)
    assert len(result.skipped_files) == 1


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"countries": ["Nigera"]}, "Did you mean 'Nigeria'"),
        ({"countries": "Nigeria", "start": "2024-1"}, "YYYY-MM"),
        ({"countries": "Nigeria", "start": "2024-05", "end": "2024-01"}, "after"),
    ],
)
def test_mistakes_get_plain_messages(archive, kwargs, message):
    with pytest.raises(ValueError, match=message):
        ni.build_index(archive, KEYWORDS, verbose=False, cache=False, **kwargs)


def test_missing_archive_folder(tmp_path):
    with pytest.raises(FileNotFoundError, match="Archive folder not found"):
        ni.build_index(tmp_path / "nowhere", KEYWORDS, "Nigeria", "2024-01", verbose=False)


def test_keyword_sheet_from_template_gives_the_same_index(archive, tmp_path):
    sheet = ni.keywords_template(tmp_path / "kw.csv", countries=TWO)
    from_sheet = ni.build_index(archive, sheet, TWO, "2024-01", "2024-04", verbose=False, cache=False)
    from_json = ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", verbose=False, cache=False)
    assert from_sheet.country.equals(from_json.country)
    assert set(from_sheet.keywords["group"]) == {"economic", "policy", "uncertainty"}


def test_keywords_as_a_dict_per_country_or_shared(archive):
    per_country = {c: {"economic": ["economy", "inflation"], "policy": ["government", "policy"],
                       "uncertainty": ["uncertainty", "risk"]} for c in TWO}
    shared = {"economic": ["economy", "inflation"], "policy": ["government", "policy"],
              "uncertainty": ["uncertainty", "risk"]}
    a = ni.build_index(archive, per_country, TWO, "2024-01", "2024-04", verbose=False, cache=False)
    b = ni.build_index(archive, shared, TWO, "2024-01", "2024-04", verbose=False, cache=False)
    assert a.country.equals(b.country)
    assert len(a.keywords) == 12


def test_missing_keyword_group_is_reported(archive):
    with pytest.raises(ValueError, match="no uncertainty keywords"):
        ni.build_index(archive, {"economic": ["economy"], "policy": ["policy"]}, "Nigeria",
                       "2024-01", "2024-04", verbose=False, cache=False)


def test_keyword_sheet_needs_its_columns(tmp_path):
    bad = tmp_path / "kw.csv"
    bad.write_text("country,word\nNigeria,economy\n")
    with pytest.raises(ValueError, match="country, group, term"):
        ni.dictionary.read(bad)


@pytest.mark.parametrize("ext", [".xlsx", ".csv", ".txt", ".json"])
def test_every_keyword_format_gives_the_same_index(archive, tmp_path, ext):
    path = ni.keywords_template(tmp_path / f"kw{ext}", countries=TWO)
    result = ni.build_index(archive, path, TWO, "2024-01", "2024-04", verbose=False, cache=False)
    expected = ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", verbose=False, cache=False)
    assert result.country.equals(expected.country)
    assert result.keywords.equals(expected.keywords)


def test_txt_keywords_by_hand(tmp_path):
    path = tmp_path / "kw.txt"
    path.write_text(
        "# my keywords\n[Nigeria]\neconomic:\neconomy\nexchange rate\npolicy: central bank\n"
        "uncertainty:\nrisk\n\n[*]\nuncertainty:\nvolatility\n",
        encoding="utf-8",
    )
    entry = ni.dictionary.read(path)["Nigeria"]
    assert entry.economic == ("economy", "exchange rate")
    assert entry.policy == ("central bank",)
    assert entry.uncertainty == ("risk", "volatility")


def test_txt_keywords_explain_a_mistake(tmp_path):
    path = tmp_path / "kw.txt"
    path.write_text("economy\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Line 1"):
        ni.dictionary.read(path)


def test_unknown_keyword_file_type(tmp_path):
    with pytest.raises(ValueError, match="Choose a keyword file format"):
        ni.keywords_template(tmp_path / "kw.docx")


def test_history_run_also_gives_the_no_history_version(archive, tmp_path, capsys):
    result = ni.build_index(archive, KEYWORDS, TWO, "2024-03", "2024-04", history=("2024-01", "2024-02"),
                            gdp=GDP, verbose=False, cache=False)
    alone = ni.build_index(archive, KEYWORDS, TWO, "2024-03", "2024-04", verbose=False, cache=False)
    assert result.no_history.equals(alone.country)          # same as a no-history-only run
    assert result.groups_no_history is not None

    result.show(version="no history")
    result.show(version="history")
    result.show()                                             # both
    text = capsys.readouterr().out
    assert "WITH HISTORY 2024-01..2024-02" in text and "NO HISTORY" in text
    assert set(result.table()["version"]) == {"with history 2024-01..2024-02", "no history"}

    out = result.save(tmp_path / "both")
    assert sorted(f.name for f in out.iterdir()) == ["epu_dashboard.html", "epu_results.xlsx"]
    kept = result.save(tmp_path / "keep", files=["dashboard", "history"])
    assert sorted(f.name for f in kept.iterdir()) == ["epu_dashboard.html", "history.json"]
    page = (out / "epu_dashboard.html").read_text(encoding="utf-8")
    assert "WITH HISTORY".lower() in page.lower() and "Keywords used" in page and "<svg" in page
    csvs = result.save(tmp_path / "csv", files="csv", version="no history")
    names = {f.name for f in csvs.iterdir()}
    assert "epu_no_history.csv" in names and "epu_history.csv" not in names
    every = result.save(tmp_path / "all", files="all")
    assert {"epu_dashboard.html", "epu_results.xlsx", "epu_chart.png"} <= {f.name for f in every.iterdir()}
    with pytest.raises(ValueError, match="files can be"):
        result.save(tmp_path / "bad", files="pdf")


def test_asking_for_a_history_version_without_one_is_explained(archive):
    result = ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", verbose=False, cache=False)
    with pytest.raises(ValueError, match="no history version"):
        result.show(version="history")


def test_relative_output_folder_goes_next_to_the_running_script(tmp_path, monkeypatch):
    import sys
    import types

    from newsindex.simple import output_folder

    script_dir = tmp_path / "project"
    script_dir.mkdir()
    fake_main = types.ModuleType("__main__")
    fake_main.__file__ = str(script_dir / "my_epu.py")
    monkeypatch.setitem(sys.modules, "__main__", fake_main)
    monkeypatch.delitem(sys.modules, "ipykernel", raising=False)
    monkeypatch.chdir(tmp_path)  # the terminal is somewhere else
    assert output_folder("my_results") == script_dir / "my_results"
    assert output_folder(tmp_path / "abs") == tmp_path / "abs"


def test_output_saves_straight_away_and_custom_regions(archive, tmp_path):
    result = ni.build_index(archive, KEYWORDS, ["Nigeria", "Morocco", "Egypt"], "2024-01", "2024-04",
                            history=("2024-01", "2024-02"), gdp=GDP, groups={"Test": ["Nigeria", "Egypt"]},
                            output=tmp_path / "out", verbose=False, cache=False)
    assert (tmp_path / "out" / "epu_dashboard.html").exists()
    assert (tmp_path / "out" / "epu_results.xlsx").exists()
    assert set(result.groups["group"]) == {"Test"}


def test_bad_groups_are_explained(archive):
    with pytest.raises(ValueError, match="groups must be a dict"):
        ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", gdp=GDP, groups=["West"], verbose=False)


# ---------------------------------------------------------------------------
# Other indices: TPU, ETU, EgPU and any 2+ keyword groups
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("index, groups", [
    (["trade", "policy", "uncertainty"], ("trade", "policy", "uncertainty")),
    (["economic", "trade", "uncertainty"], ("economic", "trade", "uncertainty")),
    (["policy", "uncertainty"], ("policy", "uncertainty")),
    (["trade", "uncertainty"], ("trade", "uncertainty")),
])
def test_other_indices_count_articles_with_every_group(archive, index, groups):
    result = ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", index=index, verbose=False, cache=False)
    kw = ni.dictionary.load()
    counts = ni.index.count_archive(archive, kw, countries=TWO, start="2024-01", end="2024-04", groups=groups)
    expected = ni.index.compute_index(counts, "2024-01", "2024-04").rename(columns={"EPU": result.measure})
    assert result.country.reset_index(drop=True).equals(expected.reset_index(drop=True))
    assert list(result.keywords["group"].unique()) == list(groups)
    assert result.measure in result.country.columns


def test_index_names_files_and_columns(archive, tmp_path):
    result = ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", index=["trade", "policy", "uncertainty"], output=tmp_path / "out",
                            verbose=False, cache=False)
    assert result.measure == "TPU" and "TPU" in result.country.columns and "tpu_articles" in result.counts.columns
    assert sorted(f.name for f in (tmp_path / "out").iterdir()) == ["tpu_dashboard.html", "tpu_results.xlsx"]
    page = (tmp_path / "out" / "tpu_dashboard.html").read_text(encoding="utf-8")
    assert "TPU index (trade + policy + uncertainty) dashboard" in page


def test_egpu_and_a_custom_index_with_own_keyword_groups(archive):
    kw = {"energy": ["oil", "fuel", "electricity", "economy"], "policy": ["policy", "government"],
          "uncertainty": ["uncertainty", "risk"], "climate": ["climate", "economy"]}
    plain = ni.build_index(archive, kw, TWO, "2024-01", "2024-04", index=["energy", "policy", "uncertainty"],
                           verbose=False, cache=False)
    assert plain.measure == "EPU"                      # just the initials: no names built in
    egpu = ni.build_index(archive, kw, TWO, "2024-01", "2024-04", index=["energy", "policy", "uncertainty"],
                          name="EgPU", verbose=False, cache=False)
    assert egpu.measure == "EgPU" and "EgPU" in egpu.country.columns
    assert egpu.country["EgPU"].equals(plain.country["EPU"])
    cpu = ni.build_index(archive, kw, TWO, "2024-01", "2024-04", index=["climate", "policy", "uncertainty"],
                         name="CPU", verbose=False, cache=False)
    assert cpu.measure == "CPU" and cpu.settings["keyword_groups"] == ["climate", "policy", "uncertainty"]


@pytest.mark.parametrize("index, message", [
    ("epu", "index must be a list of keyword groups"),
    (["policy"], "at least two keyword groups"),
    (["energy", "policy", "uncertainty"], "no energy keywords"),   # the bundled dictionary has no energy terms
])
def test_index_mistakes_are_explained(archive, index, message):
    with pytest.raises(ValueError, match=message):
        ni.build_index(archive, KEYWORDS, TWO, "2024-01", "2024-04", index=index, verbose=False, cache=False)


def test_any_group_name_in_keyword_files(tmp_path):
    path = tmp_path / "kw.txt"
    path.write_text("[Nigeria]\nenergy:\nfuel subsidy\nNote: this is a term\nclimate:\nflood\n"
                    "policy: central bank\nuncertainty:\nrisk\n", encoding="utf-8")
    entry = ni.dictionary.read(path)["Nigeria"]
    assert entry.energy == ("fuel subsidy", "Note: this is a term")
    assert entry.terms("climate") == ("flood",) and entry.policy == ("central bank",)
    sheet = tmp_path / "kw.csv"
    sheet.write_text("country,group,term\nNigeria,ENERGY_TERMS,oil\nNigeria,Climate,drought\n", encoding="utf-8")
    entry = ni.dictionary.read(sheet)["Nigeria"]
    assert entry.energy == ("oil",) and entry.terms("climate") == ("drought",)
