"""GDP files that are annual, quarterly or monthly -> one value per country and month."""

from __future__ import annotations

import math

import pandas as pd
import pytest

import CAPEnewsindex as ni
from CAPEnewsindex import aggregate
from test_fastscan import _build_messy_archive


def _long(periods, values, country="Freedonia", period_col="Period"):
    return pd.DataFrame({"Country": [country] * len(periods), period_col: periods, "GDP": values})


def _by_month(table: pd.DataFrame, **kwargs) -> pd.Series:
    out = aggregate.monthly_gdp(table, **kwargs)
    return out.set_index("year_month")["gdp"]


# --- quarterly -----------------------------------------------------------------
@pytest.mark.parametrize("labels", [
    ["2020Q1", "2020Q2"], ["2020-Q1", "2020-Q2"], ["2020 Q1", "2020 Q2"],
    ["Q1 2020", "Q2 2020"], ["2020q1", "2020q2"],
])
def test_quarterly_labels_are_placed_at_the_quarters_first_month(labels):
    table = _long(labels, [100.0, 200.0])
    out = aggregate.monthly_gdp(table)
    assert out.attrs["frequency"] == "quarterly"
    assert out.attrs["periods"] == ("2020Q1", "2020Q2")
    g = out.set_index("year_month")["gdp"]
    assert g["2020-01"] == pytest.approx(100.0)
    assert g["2020-02"] == pytest.approx(100.0 * 2 ** (1 / 3))      # log-linear: a third of the way
    assert g["2020-04"] == pytest.approx(200.0)
    assert list(g.index) == [f"2020-{m:02d}" for m in range(1, 7)]  # last quarter held flat for its 3 months
    assert g["2020-06"] == pytest.approx(200.0)


def test_year_plus_quarter_columns():
    table = pd.DataFrame({"Country": ["X"] * 3, "Year": [2020, 2020, 2020], "Quarter": ["Q1", 2, 3],
                          "GDP": [1.0, 2.0, 4.0]})
    out = aggregate.monthly_gdp(table)
    assert out.attrs["frequency"] == "quarterly"
    g = out.set_index("year_month")["gdp"]
    assert g["2020-04"] == pytest.approx(2.0) and g["2020-07"] == pytest.approx(4.0)


def test_year_col_named_with_a_quarter_column_beside_it():
    table = pd.DataFrame({"Country": ["X"] * 2, "Year": [2020, 2020], "Quarter": [1, 2], "GDP": [1.0, 2.0]})
    assert aggregate.monthly_gdp(table, year_col="Year").attrs["frequency"] == "quarterly"


# --- monthly -------------------------------------------------------------------
@pytest.mark.parametrize("labels", [
    [202001, 202002], ["202001", "202002"], ["2020-01", "2020-02"], ["2020/01", "2020/02"],
    ["2020M01", "2020M02"], ["01/2020", "02/2020"], ["Jan 2020", "Feb 2020"], ["January 2020", "February 2020"],
])
def test_monthly_labels_are_used_as_is(labels):
    out = aggregate.monthly_gdp(_long(labels, [100.0, 110.0]))
    assert out.attrs["frequency"] == "monthly"
    g = out.set_index("year_month")["gdp"]
    assert list(g.index) == ["2020-01", "2020-02"]
    assert list(g) == pytest.approx([100.0, 110.0])


def test_missing_months_are_filled_log_linearly_and_the_last_is_carried_to_end():
    g = _by_month(_long(["2020-01", "2020-03"], [100.0, 400.0]), end="2020-05")
    assert g["2020-02"] == pytest.approx(200.0)
    assert g["2020-05"] == pytest.approx(400.0)


def test_year_plus_month_columns():
    table = pd.DataFrame({"Country": ["X"] * 2, "Year": [2020, 2020], "Month": ["Jan", 2], "GDP": [1.0, 2.0]})
    assert aggregate.monthly_gdp(table).attrs["frequency"] == "monthly"


def test_a_month_column_holding_full_labels():
    table = pd.DataFrame({"Country": ["X"] * 2, "Month": ["2020-01", "2020-02"], "GDP": [1.0, 2.0]})
    assert aggregate.monthly_gdp(table).attrs["frequency"] == "monthly"


# --- annual (unchanged behaviour) ----------------------------------------------
def test_annual_is_still_january_to_january():
    out = aggregate.monthly_gdp(pd.DataFrame({"Country": ["X", "X"], "Year": [2020, 2021], "GDP": [100.0, 200.0]}))
    assert out.attrs["frequency"] == "annual"
    g = out.set_index("year_month")["gdp"]
    assert g["2020-07"] == pytest.approx(math.sqrt(100 * 200))
    assert g["2021-12"] == pytest.approx(200.0)


def test_a_missing_year_is_bridged_not_left_as_a_hole():
    g = _by_month(pd.DataFrame({"Country": ["X", "X"], "Year": [2020, 2022], "GDP": [100.0, 400.0]}))
    assert g["2021-01"] == pytest.approx(200.0)
    assert len(g) == 36


# --- full dates ------------------------------------------------------------------
@pytest.mark.parametrize("dates,frequency", [
    (["2020-01-01", "2021-01-01", "2022-01-01"], "annual"),
    (["2020-03-31", "2020-06-30", "2020-09-30"], "quarterly"),
    (["1/1/2020", "2/1/2020", "3/1/2020"], "monthly"),
])
def test_dates_get_their_frequency_from_the_spacing(dates, frequency):
    out = aggregate.monthly_gdp(_long(dates, [1.0, 2.0, 3.0], period_col="Date"))
    assert out.attrs["frequency"] == frequency


def test_quarter_end_dates_belong_to_their_quarter():
    g = _by_month(_long(["2020-03-31", "2020-06-30"], [1.0, 2.0], period_col="Date"))
    assert g.index[0] == "2020-01" and g["2020-04"] == pytest.approx(2.0)


def test_excel_datetimes_and_stated_frequency():
    dates = pd.to_datetime(["2020-02-15", "2020-05-15"])
    out = aggregate.monthly_gdp(_long(list(dates), [1.0, 2.0], period_col="Date"), frequency="quarterly")
    assert out.attrs["frequency"] == "quarterly"
    assert out["year_month"].iloc[0] == "2020-01"


def test_one_date_per_country_needs_the_frequency_stated():
    with pytest.raises(ValueError, match="frequency"):
        aggregate.monthly_gdp(_long(["2020-01-01"], [1.0], period_col="Date"))
    assert aggregate.monthly_gdp(_long(["2020-01-01"], [1.0], period_col="Date"),
                                 frequency="annual").attrs["frequency"] == "annual"


# --- wide layout -------------------------------------------------------------------
def test_wide_file_one_column_per_country(tmp_path):
    path = tmp_path / "gdp_wide.csv"
    path.write_text("date,Algeria,Angola\n1/1/2020,10,5\n2/1/2020,11,\n3/1/2020,12,6\n", encoding="utf-8")
    out = aggregate.monthly_gdp(path, end="2020-04")
    assert out.attrs["frequency"] == "monthly" and out.attrs["countries"] == 2
    g = out.set_index(["country", "year_month"])["gdp"]
    assert g["Algeria", "2020-03"] == pytest.approx(12.0)
    assert g["Angola", "2020-02"] == pytest.approx(math.sqrt(30))   # blank month bridged
    assert g["Angola", "2020-04"] == pytest.approx(6.0)


def test_wide_quarterly():
    table = pd.DataFrame({"Quarter": ["2020Q1", "2020Q2"], "Kenya": [1.0, 2.0], "Ghana": [3.0, 4.0]})
    out = aggregate.monthly_gdp(table)
    assert out.attrs["frequency"] == "quarterly" and set(out["country"]) == {"Kenya", "Ghana"}


# --- errors ------------------------------------------------------------------------
def test_mixed_frequencies_are_refused():
    with pytest.raises(ValueError, match="mixes frequencies"):
        aggregate.monthly_gdp(_long(["2020", "2021Q1"], [1.0, 2.0]))


def test_stated_frequency_must_match_the_labels():
    with pytest.raises(ValueError, match='frequency="annual" but the periods look quarterly'):
        aggregate.monthly_gdp(_long(["2020Q1", "2020Q2"], [1.0, 2.0]), frequency="annual")


def test_bad_frequency_word():
    with pytest.raises(ValueError, match="frequency must be"):
        aggregate.monthly_gdp(_long(["2020"], [1.0]), frequency="weekly")


def test_two_values_for_one_period_are_refused():
    with pytest.raises(ValueError, match="Two different values"):
        aggregate.monthly_gdp(_long(["2020Q1", "2020-Q1"], [1.0, 2.0]))


def test_unreadable_periods_are_named():
    with pytest.raises(ValueError, match="Can't read these periods"):
        aggregate.monthly_gdp(_long(["2020H1", "2020H2"], [1.0, 2.0]))


def test_long_file_with_an_unknown_country_column_asks_for_it():
    table = pd.DataFrame({"Nation": ["X", "Y"], "Year": [2020, 2020], "GDP": [1.0, 2.0]})
    with pytest.raises(ValueError, match="country_col"):
        aggregate.monthly_gdp(table)
    assert set(aggregate.monthly_gdp(table, country_col="Nation")["country"]) == {"X", "Y"}


# --- population and build_index -------------------------------------------------
def test_population_accepts_quarterly_too():
    table = pd.DataFrame({"Country": ["X", "X"], "Quarter": ["2020Q1", "2020Q2"], "Population": [1.0, 2.0]})
    out = ni.weights.population(table)
    assert "population" in out.columns and out.attrs["frequency"] == "quarterly"


@pytest.fixture
def archive(tmp_path):
    _build_messy_archive(tmp_path / "archive", 11)
    return tmp_path / "archive"


def test_build_index_reports_the_gdp_frequency(archive, capsys):
    gdp = pd.DataFrame({"Country": ["Nigeria"] * 4 + ["Morocco"] * 4,
                        "Quarter": ["2023Q4", "2024Q1", "2024Q2", "2024Q3"] * 2,
                        "GDP": [1.0, 1.1, 1.2, 1.3, 2.0, 2.1, 2.2, 2.3]})
    result = ni.build_index(archive, ni.dictionary.TEMPLATE_PATH, ["Nigeria", "Morocco"], "2024-01", "2024-04",
                            gdp=gdp, cache=False)
    assert "GDP: quarterly, 2023Q4..2024Q3, 2 countries" in capsys.readouterr().out
    assert result.settings["gdp_frequency"] == "quarterly"
    assert result.settings["gdp_periods"] == "2023Q4..2024Q3"
    assert result.groups is not None and not result.groups.empty


def test_build_index_gdp_frequency_is_checked(archive):
    gdp = pd.DataFrame({"Country": ["Nigeria", "Nigeria"], "Year": [2023, 2024], "GDP": [1.0, 2.0]})
    with pytest.raises(ValueError, match='frequency="monthly" but the periods look annual'):
        ni.build_index(archive, ni.dictionary.TEMPLATE_PATH, ["Nigeria", "Morocco"], "2024-01", "2024-04",
                       gdp=gdp, gdp_frequency="monthly", verbose=False, cache=False)
