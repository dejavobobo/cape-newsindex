"""Country z-scores, weighting, and group indices for blocks of countries you define.

Four steps: standardise each country's index against its own scaling period,
weight by within-group share (GDP by default, or any table or custom weighting
function -- see :func:`aggregate`), take the weighted average of the country
z-scores, and rescale the result to a scaling-period mean of 100 and standard
deviation of 10. Each group is computed from its countries directly, so a large
group is not an average of smaller ones.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Annual, quarterly or monthly GDP (or population, ...) -> one value per month
# ---------------------------------------------------------------------------
#: The frequencies a GDP file can have, and the months each period spans.
FREQUENCIES = {"annual": 12, "quarterly": 3, "monthly": 1}
_FREQ_ALIASES = {
    "auto": "auto", "": "auto",
    "annual": "annual", "a": "annual", "y": "annual", "yearly": "annual", "year": "annual",
    "quarterly": "quarterly", "q": "quarterly", "quarter": "quarterly",
    "monthly": "monthly", "m": "monthly", "month": "monthly",
}
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTH_NAME = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

# Each label is read as (kind, year, sub): kind "A" year, "Q" quarter (sub 1-4),
# "M" month (sub 1-12), or "D" a full date (sub = month), whose frequency is
# worked out from the spacing of the dates.
_LABELS = [
    (re.compile(r"^(\d{4})$"), lambda m: ("A", int(m[1]), None)),
    (re.compile(r"^(\d{4})\s*[-_/. ]?\s*q([1-4])$"), lambda m: ("Q", int(m[1]), int(m[2]))),
    (re.compile(r"^q([1-4])\s*[-_/. ]?\s*(\d{4})$"), lambda m: ("Q", int(m[2]), int(m[1]))),
    (re.compile(r"^(\d{4})(\d{2})$"), lambda m: ("M", int(m[1]), int(m[2]))),
    (re.compile(r"^(\d{4})\s*(?:[-/.]|m)\s*(\d{1,2})$"), lambda m: ("M", int(m[1]), int(m[2]))),
    (re.compile(r"^(\d{1,2})\s*[-/.]\s*(\d{4})$"), lambda m: ("M", int(m[2]), int(m[1]))),
    (re.compile(rf"^{_MONTH_NAME}\s*[-_/., ]?\s*(\d{{4}})$"), lambda m: ("M", int(m[2]), _MONTHS[m[1]])),
    (re.compile(rf"^(\d{{4}})\s*[-_/., ]?\s*{_MONTH_NAME}$"), lambda m: ("M", int(m[1]), _MONTHS[m[2]])),
]
_KIND_FREQ = {"A": "annual", "Q": "quarterly", "M": "monthly"}
_UNIT = {"annual": "year", "quarterly": "quarter", "monthly": "month"}
FORMATS_HELP = (
    "annual 2015; quarterly 2015Q1, 2015-Q1, 2015 Q1, Q1 2015; monthly 201501, 2015-01, 2015/01, "
    "2015M01, 01/2015, Jan 2015; a full date such as 2015-01-01 or 1/1/2015; or separate "
    "Year + Quarter (1-4 or Q1) or Year + Month (1-12 or Jan) columns"
)


def _text(value) -> str:
    """A period label as clean text (Excel gives 2015.0 for 2015, datetimes for dates)."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip().lower()


def _parse_label(value):
    """One period label -> (kind, year, sub), or None if it isn't one."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, pd.Period):
        f = value.freqstr.upper()
        if f.startswith(("A", "Y")):
            return ("A", value.year, None)
        if f.startswith("Q"):
            return ("Q", value.year, value.quarter)
        if f.startswith("M"):
            return ("M", value.year, value.month)
        value = value.to_timestamp()
    if isinstance(value, (pd.Timestamp, np.datetime64)) or hasattr(value, "year") and hasattr(value, "month"):
        stamp = pd.Timestamp(value)
        return ("D", stamp.year, stamp.month)
    text = _text(value)
    for pattern, make in _LABELS:
        m = pattern.match(text)
        if m:
            kind, year, sub = make(m)
            if kind == "M" and not 1 <= sub <= 12:
                return None
            return kind, year, sub
    if re.search(r"\d{4}", text) or re.search(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", text):
        try:
            stamp = pd.Timestamp(text)  # month-first for 1/4/2015 (= 4 January 2015)
        except (ValueError, TypeError):
            return None
        if pd.isna(stamp):
            return None
        return ("D", stamp.year, stamp.month)
    return None


def _parse_part(value, kind: str):
    """A separate Quarter (1-4, Q1) or Month (1-12, Jan) value -> its number, or None."""
    text = _text(value)
    if kind == "Q":
        m = re.match(r"^q?([1-4])$", text)
        return int(m[1]) if m else None
    if text.isdigit() and 1 <= int(text) <= 12:
        return int(text)
    m = re.match(rf"^{_MONTH_NAME}$", text)
    return _MONTHS[m[1]] if m else None


def _norm(name) -> str:
    return re.sub(r"[^a-z]", "", str(name).lower())


def _find(columns, wanted: tuple[str, ...], given: str | None, what: str):
    if given is not None:
        if given not in columns:
            raise ValueError(f"The {what} column {given!r} is not in the file. Columns found: {list(columns)}")
        return given
    return next((c for c in columns if _norm(c) in wanted), None)


def _read_table(source) -> pd.DataFrame:
    if isinstance(source, pd.DataFrame):
        return source.copy()
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"GDP file not found: {path}")
    return pd.read_excel(path) if path.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(path)


def read_periodic(
    source: str | Path | pd.DataFrame,
    *,
    country_col: str | None = None,
    period_col: str | None = None,
    value_col: str | None = None,
    frequency: str = "auto",
    prefer: str = "gdp",
) -> tuple[pd.DataFrame, str]:
    """Read an annual, quarterly or monthly by-country table.

    Returns ``(table, frequency)``: ``table`` has ``country``, ``start``
    (the period's first month as a month number, year * 12 + month - 1),
    ``label`` (the period as written in the file) and ``value``;
    ``frequency`` is ``"annual"``, ``"quarterly"`` or ``"monthly"``.

    Long files have a country column, a period column and a value column.
    Wide files have a period column and one column per country (like a
    ``date, Algeria, Angola, ...`` sheet). Columns are found by name unless
    you name them: the country column is called country (or Country_Name,
    ...); the period column year, quarter, month, date, period, time or
    year_month -- or Year plus a separate Quarter or Month column; the value
    column is the numeric column whose name contains ``prefer`` (e.g. gdp),
    else the first numeric column. See :data:`FORMATS_HELP` for the labels.

    ``frequency="auto"`` (default) takes it from the labels -- 2015 is
    annual, 2015Q1 quarterly, 2015-01 monthly; full dates go by their
    spacing (12 months apart = annual, 3 = quarterly, 1 = monthly). Give
    ``"annual"``, ``"quarterly"`` or ``"monthly"`` to state it: full dates
    are then put in that period (2015-03-31 -> 2015Q1), and labels of
    another frequency are an error.
    """
    freq = _FREQ_ALIASES.get(str(frequency).strip().lower())
    if freq is None:
        raise ValueError(f'frequency must be "auto", "annual", "quarterly" or "monthly", not {frequency!r}.')
    raw = _read_table(source)
    if raw.empty:
        raise ValueError("The GDP file is empty.")
    cols = list(raw.columns)

    country = _find(cols, ("country", "countries", "countryname", "name", "economy"), country_col, "country")
    if country is None and country_col is None:
        country = next((c for c in cols if "country" in str(c).lower() and "code" not in str(c).lower()), None)
    year = qcol = mcol = None
    period = _find(cols, ("date", "period", "time", "yearmonth", "ym", "yearquarter", "yq", "monthyear",
                          "quarteryear", "datetime", "yyyymm"), period_col, "period")
    if period is not None and raw[period].dropna().map(lambda v: (_parse_label(v) or ("",))[0] == "A").all():
        year, period = period, None  # a year column: there may be a Quarter or Month column beside it
    if period is None:
        if year is None:
            year = _find(cols, ("year", "yr", "years"), None, "year")
        if year is None:
            year = next((c for c in cols if "year" in str(c).lower()), None)
        qcol = _find(cols, ("quarter", "qtr", "q"), None, "quarter")
        mcol = _find(cols, ("month", "mon", "m"), None, "month")
        sub = qcol or mcol
        if sub is not None and year is not None:
            kind = "Q" if sub == qcol else "M"
            if not raw[sub].dropna().map(lambda v: _parse_part(v, kind) is not None).all():
                period, year, qcol, mcol = sub, None, None, None  # e.g. Month = "2015-01": the full label
        elif sub is not None:
            period, qcol, mcol = sub, None, None
        else:
            period, year = year, None
    if period is None and year is None:
        raise ValueError(
            "The GDP file needs a period column (year, quarter, month, date or period). "
            f"Columns found: {cols}. Accepted periods: {FORMATS_HELP}."
        )

    used = {c for c in (country, period, year, qcol, mcol) if c is not None}
    numeric = [c for c in cols if c not in used and pd.api.types.is_numeric_dtype(raw[c])]
    if country is None:  # wide: one column per country
        if value_col is not None:
            raise ValueError("value_col is for long files (a country column, a period column, a value column).")
        if not numeric:
            raise ValueError(f"The GDP file needs a country column or one numeric column per country. Columns: {cols}")
        keys = [c for c in (period, year, qcol, mcol) if c is not None]
        other = [c for c in cols if c not in keys and c not in numeric]
        if other:
            raise ValueError(
                f"No country column found (columns: {cols}). Name it with country_col=..., "
                "or use a wide file: a period column and one numeric column per country."
            )
        raw = raw.melt(id_vars=keys, value_vars=numeric, var_name="__country", value_name="__value")
        country, value = "__country", "__value"
    else:
        if value_col is not None:
            if value_col not in cols:
                raise ValueError(f"The value column {value_col!r} is not in the file. Columns found: {cols}")
            value = value_col
        else:
            value = next((c for c in numeric if prefer and prefer in str(c).lower()), numeric[0] if numeric else None)
        if value is None:
            raise ValueError(
                "The GDP file needs a country column, a period column and one numeric GDP column "
                f"(e.g. Country, Year, GDP). Columns found: {cols}"
            )

    # --- the periods ---------------------------------------------------------
    if period is not None:
        labels = raw[period]
        parsed = {v: _parse_label(v) for v in labels.dropna().unique()}
        bad = [v for v, p in parsed.items() if p is None]
        if bad:
            raise ValueError(f"Can't read these periods in column {period!r}: {bad[:5]}. Accepted: {FORMATS_HELP}.")
        keys = labels.map(lambda v: parsed.get(v))
        shown = labels.map(lambda v: str(v).strip())
    else:
        kind = "Q" if qcol is not None else "M"
        sub = qcol or mcol
        y = raw[year].map(_parse_label)
        if y.dropna().map(lambda p: p[0] != "A").any():
            raise ValueError(f"The {year!r} column should hold years like 2015.")
        parts = raw[sub].map(lambda v: _parse_part(v, kind))
        keys = pd.Series([(kind, p[1], s) if p is not None and s is not None else None for p, s in zip(y, parts)],
                         index=raw.index)
        shown = keys.map(lambda k: None if k is None else (f"{k[1]}Q{k[2]}" if kind == "Q" else f"{k[1]}-{k[2]:02d}"))

    table = pd.DataFrame({"country": raw[country], "key": keys, "label": shown,
                          "value": pd.to_numeric(raw[value], errors="coerce")})
    table = table[table["country"].notna() & table["key"].notna() & table["value"].notna()].copy()
    if table.empty:
        raise ValueError("The GDP file has no rows with a country, a period and a number.")
    table["country"] = table["country"].astype(str).str.strip()

    kinds = sorted({k[0] for k in table["key"]})
    if len(kinds) > 1:
        examples = {k: table.loc[table["key"].map(lambda x: x[0] == k), "label"].iloc[0] for k in kinds}
        names = {"A": "annual", "Q": "quarterly", "M": "monthly", "D": "full dates"}
        raise ValueError(
            "The GDP file mixes frequencies ("
            + ", ".join(f"{names[k]} e.g. {examples[k]!r}" for k in kinds)
            + "). Use one frequency for every row and country."
        )
    kind = kinds[0]
    if kind == "D":
        found = _date_frequency(table) if freq == "auto" else freq
    else:
        found = _KIND_FREQ[kind]
        if freq not in ("auto", found):
            raise ValueError(f'frequency="{freq}" but the periods look {found} (e.g. {table["label"].iloc[0]!r}).')

    span = FREQUENCIES[found]
    table["start"] = table["key"].map(lambda k: k[1] * 12 + (_first_month(k) - 1) // span * span)
    dup = table[table.duplicated(["country", "start"], keep=False)]
    dup = dup.groupby(["country", "start"]).filter(lambda g: g["value"].nunique() > 1)
    if not dup.empty:
        first = dup.iloc[0]
        raise ValueError(
            f"Two different values for {first['country']} in the same {_UNIT[found]} "
            f"({', '.join(dup[(dup['country'] == first['country']) & (dup['start'] == first['start'])]['label'])}). "
            "Keep one row per country and period"
            + (" -- or give frequency=\"monthly\"/\"quarterly\" if these are finer periods." if kind == "D" else ".")
        )
    table = table.drop_duplicates(["country", "start"]).sort_values(["country", "start"])
    return table[["country", "start", "label", "value"]].reset_index(drop=True), found


def _first_month(key) -> int:
    """The month (1-12) a parsed label starts in."""
    kind, _, sub = key
    return 1 if kind == "A" else (sub - 1) * 3 + 1 if kind == "Q" else sub


def _date_frequency(table: pd.DataFrame) -> str:
    """Annual, quarterly or monthly, from how far apart each country's dates are."""
    months = table.assign(t=table["key"].map(lambda k: k[1] * 12 + k[2] - 1))
    gaps = months.drop_duplicates(["country", "t"]).sort_values(["country", "t"]).groupby("country")["t"].diff().dropna()
    if gaps.empty:
        raise ValueError('Can\'t tell the frequency from a single date per country: give frequency="annual", '
                         '"quarterly" or "monthly".')
    gap = float(gaps.median())
    if gap >= 10:
        return "annual"
    if 2.5 <= gap <= 4:
        return "quarterly"
    if gap <= 1.5:
        return "monthly"
    raise ValueError(f"The dates are about {gap:g} months apart -- not annual, quarterly or monthly. "
                     'Give frequency="annual", "quarterly" or "monthly".')


def _month_label(t: int) -> str:
    return f"{t // 12}-{t % 12 + 1:02d}"


def _period_label(t: int, frequency: str) -> str:
    """A period's first month -> 2015, 2015Q1 or 2015-01."""
    if frequency == "annual":
        return str(t // 12)
    if frequency == "quarterly":
        return f"{t // 12}Q{t % 12 // 3 + 1}"
    return _month_label(t)


def _to_monthly(
    source: str | Path | pd.DataFrame,
    *,
    country_col: str | None,
    period_col: str | None,
    value_col: str | None,
    scale: float,
    end: str | None,
    aliases: dict[str, str] | None,
    output_col: str,
    frequency: str = "auto",
    prefer: str = "gdp",
) -> pd.DataFrame:
    """Shared body of :func:`monthly_gdp` and :func:`CAPEnewsindex.weights.population`.

    Each period's value is placed at the period's first month (January for
    a year; January, April, July or October for a quarter; the month itself
    for monthly data) and interpolated linearly in logarithms to the next
    period's value. After a country's last figure, the value is held flat
    to the end of that period and then, with ``end``, through ``end``.
    The result carries ``attrs["frequency"]`` and ``attrs["periods"]``.
    """
    table, found = read_periodic(source, country_col=country_col, period_col=period_col, value_col=value_col,
                                 frequency=frequency, prefer=prefer)
    if aliases:  # only the renames you ask for, e.g. {"Burkina Faso": "Burkina-Faso"}
        table["country"] = table["country"].map(lambda c: aliases.get(c, c))
        table = table.drop_duplicates(["country", "start"])
    span = FREQUENCIES[found]
    last_month = None
    if end is not None:
        y, m = str(end)[:7].split("-")
        last_month = int(y) * 12 + int(m) - 1

    rows: list[tuple[str, str, float]] = []
    for country, group in table.groupby("country", sort=True):
        points = list(zip(group["start"], group["value"].astype(float) * scale))
        for i, (t0, v0) in enumerate(points):
            if i + 1 < len(points):
                t1, v1 = points[i + 1]
                for t in range(t0, t1):
                    frac = (t - t0) / (t1 - t0)
                    v = float(np.exp(np.log(v0) + frac * (np.log(v1) - np.log(v0)))) if v0 > 0 and v1 > 0 else v0
                    rows.append((country, _month_label(t), v))
            else:
                stop = t0 + span - 1
                if last_month is not None:
                    stop = max(stop, last_month)
                rows.extend((country, _month_label(t), v0) for t in range(t0, stop + 1))

    result = pd.DataFrame(rows, columns=["country", "year_month", output_col])
    result = result.sort_values(["country", "year_month"]).reset_index(drop=True)
    result.attrs["frequency"] = found
    result.attrs["periods"] = (_period_label(int(table["start"].min()), found),
                               _period_label(int(table["start"].max()), found))
    result.attrs["countries"] = int(table["country"].nunique())
    return result


def monthly_gdp(
    source: str | Path | pd.DataFrame,
    *,
    country_col: str | None = None,
    year_col: str | None = None,
    value_col: str | None = None,
    frequency: str = "auto",
    scale: float = 1.0,
    end: str | None = None,
    aliases: dict[str, str] | None = None,
    period_col: str | None = None,
) -> pd.DataFrame:
    """Turn annual, quarterly or monthly GDP (or any other by-country
    figure) into one value per country and month.

    ``source`` is a CSV or Excel file, or a DataFrame. GDP data is not
    bundled: you always supply your own. Accepted layouts and period labels:

    - long: a country column, a period column, a value column, e.g.
      ``Country, Year, GDP`` or ``Country, Quarter, GDP`` (2015Q1) or
      ``Country, Month, GDP`` (201501 / 2015-01) or ``Country, Year, Quarter, GDP``;
    - wide: a period column and one column per country (``date, Algeria, Angola, ...``).

    Columns are found by name; name them yourself with ``country_col``,
    ``period_col`` (``year_col`` is the same thing, kept for older code)
    and ``value_col``.

    ``frequency`` -- ``"auto"`` (default: read from the labels; full dates
    by their spacing) or ``"annual"``, ``"quarterly"``, ``"monthly"``.
    The frequency used is in ``result.attrs["frequency"]``.

    Each value is placed at its period's first month (January; January,
    April, July or October; or the month itself) and interpolated linearly
    in logarithms to the next value, so weights move smoothly. Missing
    months inside monthly data are filled the same way. After a country's
    last figure the value is held flat to the end of that period and then,
    with ``end`` (``"YYYY-MM"``), through ``end``. Months before a country's
    first figure get no value.

    ``scale`` multiplies every value, e.g. ``scale=1000`` for billions to
    millions. ``aliases`` renames countries to match your archive's folder
    names, e.g. ``{"Burkina Faso": "Burkina-Faso"}``. Nothing is renamed
    otherwise.
    """
    if year_col is not None and period_col is not None and year_col != period_col:
        raise ValueError("Give period_col or year_col, not both.")
    return _to_monthly(
        source,
        country_col=country_col,
        period_col=period_col or year_col,
        value_col=value_col,
        scale=scale,
        end=end,
        aliases=aliases,
        output_col="gdp",
        frequency=frequency,
        prefer="gdp",
    )


def _population_stats(series: pd.Series) -> tuple[float, float]:
    values = series.to_numpy(dtype=float)
    return float(np.mean(values)), float(np.std(values, ddof=0))


def aggregate(
    country_index: pd.DataFrame,
    weights: pd.DataFrame | Callable[[pd.DataFrame, str], pd.Series],
    groups: dict[str, list[str]] | None = None,
    *,
    weight_col: str = "gdp",
    value: str | None = None,
    history=None,
    history_start: str | None = None,
    history_end: str | None = None,
) -> pd.DataFrame:
    """Weighted group indices for the blocks of countries you define.

    ``country_index`` has ``country``, ``year_month`` and the index column
    (``EPU``, ``TPU``, ... -- found automatically, or name it with ``value``),
    as produced by :func:`CAPEnewsindex.index.score` or :func:`CAPEnewsindex.build_index`.

    ``groups`` is ``{"Block name": [countries], ...}``; a country may be in
    several blocks. Without ``groups``, all countries form one block, "All countries".

    ``weights`` controls how countries are combined within each group, and
    is either:

    - A DataFrame with ``country``, ``year_month``, and a weight-value
      column (``weight_col``, default ``"gdp"`` -- the column name
      produced by :func:`monthly_gdp`). Only countries present in this
      table are included. Within each group and month, countries are
      weighted by their share of the group's total.
    - A callable ``weights(month_rows, group_name) -> pandas.Series``,
      called once per group per month with that month's rows for the
      group (columns include ``country`` and ``z``) and the group's name,
      returning a non-negative weight per row (aligned to
      ``month_rows.index``). Weights don't need to be pre-normalised --
      they are divided by their own sum -- so e.g. equal weighting is
      ``lambda rows, group: pandas.Series(1.0, index=rows.index)``.

    The scaling period: pass the :class:`CAPEnewsindex.index.History` used to
    score ``country_index`` as ``history`` to reuse its window, or give
    ``history_start``/``history_end``. Without either, all months in
    ``country_index`` are the scaling period (the no-history version).
    """
    from .index import value_column

    value = value or value_column(country_index)
    if history is not None:
        history_start, history_end = history.start, history.end
    months = country_index["year_month"].astype(str)
    history_start = history_start or months.min()
    history_end = history_end or months.max()
    if groups is None:
        groups = {"All countries": sorted(country_index["country"].unique())}
    if callable(weights):
        merged = country_index.copy()
    else:
        merged = country_index.merge(weights, on=["country", "year_month"], how="inner")

    history_window = merged[
        (merged["year_month"] >= history_start) & (merged["year_month"] <= history_end)
    ]
    country_stats = {
        country: _population_stats(rows[value])
        for country, rows in history_window.groupby("country")
        if len(rows) >= 2
    }

    merged = merged[merged["country"].isin(country_stats)].copy()
    merged["m_c"] = merged["country"].map(lambda c: country_stats[c][0])
    merged["s_c"] = merged["country"].map(lambda c: country_stats[c][1])
    merged = merged[merged["s_c"] > 0]
    merged["z"] = (merged[value] - merged["m_c"]) / merged["s_c"]

    all_groups = dict(groups)

    group_rows: list[dict] = []
    for group_name, members in all_groups.items():
        group_data = merged[merged["country"].isin(members)]
        for year_month, month_rows in group_data.groupby("year_month"):
            raw_weight = weights(month_rows, group_name) if callable(weights) else month_rows[weight_col]
            total_weight = raw_weight.sum()
            if total_weight <= 0:
                continue
            weight = raw_weight / total_weight
            z_weighted = float((weight * month_rows["z"]).sum())
            group_rows.append(
                {
                    "group": group_name,
                    "year_month": year_month,
                    "Z": z_weighted,
                    "n_countries": int(month_rows["country"].nunique()),
                    "weight_covered": float(total_weight),
                }
            )

    regional = pd.DataFrame(group_rows, columns=["group", "year_month", "Z", "n_countries", "weight_covered"])
    if regional.empty:
        return regional.rename(columns={"Z": "z"}).assign(index=pd.Series(dtype=float))

    output_rows: list[dict] = []
    for group_name, rows in regional.groupby("group"):
        window = rows[(rows["year_month"] >= history_start) & (rows["year_month"] <= history_end)]
        if len(window) < 2:
            continue
        m_r, s_r = _population_stats(window["Z"])
        if s_r <= 0:
            continue
        for _, row in rows.iterrows():
            output_rows.append(
                {
                    "group": group_name,
                    "year_month": row["year_month"],
                    "z": row["Z"],
                    "index": 100.0 + 10.0 * (row["Z"] - m_r) / s_r,
                    "n_countries": row["n_countries"],
                    "weight_covered": row["weight_covered"],
                }
            )

    result = pd.DataFrame(
        output_rows, columns=["group", "year_month", "z", "index", "n_countries", "weight_covered"]
    )
    return result.sort_values(["group", "year_month"]).reset_index(drop=True)
