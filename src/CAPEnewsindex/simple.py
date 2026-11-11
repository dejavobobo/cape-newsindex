"""The simple way to use CAPEnewsindex: one call, readable output, everything checked for you.

.. code-block:: python

    import CAPEnewsindex as ni

    result = ni.build_index(
        archive=r"C:\\path\\to\\Scrapped_Top_Articles",
        keywords="my_keywords.xlsx",      # your keywords: country, group, term
        countries=["Nigeria", "Ghana"],
        start="2024-01",
        end="2026-09",
    )
    result.show()               # summary per country + latest months
    result.plot()               # one line per country
    result.save("my_results")   # HTML dashboard + Excel workbook

Add ``history=("2015-01", "2024-12")`` to scale the index on that history
period and score ``start``..``end`` against it (you get the no-history
version too), and ``gdp="my_gdp.csv"`` with ``groups={"Block": [countries]}``
to also get GDP-weighted indices for blocks of countries you define.
Everything else (checks, cores, caching, file problems) is handled for you.
To start a keyword sheet from a template, run
``ni.keywords_template("my_keywords.xlsx")`` once and edit the file.
"""

from __future__ import annotations

import difflib
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import aggregate as _aggregate
from . import dictionary as _dictionary
from . import index as _index
from ._version import __version__
from .fastscan import collapse_folders, count_archive_fast

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _index_spec(index, name=None) -> tuple[str, str, tuple[str, ...]]:
    """(name, title, groups) from ``index`` (2+ keyword groups) and an optional ``name``.

    Without a name the index is called by the initials of its groups
    (economic, policy, uncertainty -> "EPU").
    """
    if isinstance(index, str) or not isinstance(index, (list, tuple)):
        raise ValueError('index must be a list of keyword groups, e.g. ["economic", "policy", "uncertainty"] '
                         f'or ["policy", "uncertainty"] (got {index!r}).')
    groups = tuple(dict.fromkeys(_dictionary.group_name(g) for g in index))
    if len(groups) < 2:
        raise ValueError('An index needs at least two keyword groups, e.g. ["policy", "uncertainty"].')
    label = str(name).strip() if name is not None and str(name).strip() else "".join(g[0].upper() for g in groups)
    if not label.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"name must be letters and digits, e.g. \"EgPU\" (got {name!r}).")
    return label, f"{label} index ({' + '.join(groups)})", groups


def _say(verbose: bool, message: str = "") -> None:
    if verbose:
        print(message, flush=True)


# ---------------------------------------------------------------------------
# Input checks with plain-language messages
# ---------------------------------------------------------------------------
def _check_month(value, name: str) -> str:
    text = str(value).strip()
    if not _MONTH.match(text):
        raise ValueError(f'{name} must be a month written as "YYYY-MM", e.g. "2024-01" (got {value!r}).')
    return text


def _did_you_mean(name: str, options) -> str:
    close = difflib.get_close_matches(name, list(options), n=3, cutoff=0.6)
    if not close:
        close = [o for o in options if name.lower() in o.lower() or o.lower() in name.lower()][:3]
    return f" Did you mean {', '.join(repr(c) for c in close)}?" if close else ""


def _resolve(archive: Path, countries, kw: _dictionary.Dictionary, groups=_dictionary.EPU_GROUPS) -> list[str]:
    shared = kw.countries.get("*")
    folders = sorted(p.name for p in archive.iterdir() if p.is_dir())
    if not folders:
        raise FileNotFoundError(f"The archive folder has no country folders inside it: {archive}")
    if countries is None or (isinstance(countries, str) and countries.lower() == "all"):
        wanted = folders
    else:
        wanted = [countries] if isinstance(countries, str) else list(countries)
    by_lower = {f.lower(): f for f in folders}
    resolved, problems = [], []
    for name in wanted:
        folder = by_lower.get(str(name).strip().lower())
        if folder is None:
            problems.append(f"  - {name!r}: no folder with this name in the archive.{_did_you_mean(str(name), folders)}")
            continue
        if folder not in kw and shared is None:
            match = {c.lower(): c for c in kw.countries}.get(folder.lower())
            hint = (f" Your keywords spell it {match!r}; use the folder name {folder!r} there."
                    if match else _did_you_mean(folder, kw.countries))
            problems.append(f"  - {folder!r}: has no keywords.{hint}")
            continue
        if folder not in resolved:
            resolved.append(folder)
    for folder in resolved:
        entry = kw.countries.get(folder, shared)
        empty = [g for g in groups if not entry.terms(g)]
        if empty:
            problems.append(f"  - {folder!r}: no {' / '.join(empty)} keywords (an article must match every group: "
                            f"{', '.join(groups)}).")
    if problems:
        raise ValueError("Some countries can't be used:\n" + "\n".join(problems))
    return resolved


def _for_countries(kw: _dictionary.Dictionary, countries: list[str], groups) -> _dictionary.Dictionary:
    """The keywords actually used: the required groups of each selected country ('*' expanded)."""
    shared = kw.countries.get("*")
    picked = {}
    for c in countries:
        entry = kw.countries.get(c, shared)
        picked[c] = _dictionary.CountryDictionary(
            country=c, groups={g: entry.terms(g) for g in groups}, languages=entry.languages,
        )
    return _dictionary.Dictionary(countries=picked, source=kw.source)


def _read_gdp(gdp, end: str, names: dict[str, str] | None = None) -> pd.DataFrame:
    table = gdp
    if not isinstance(gdp, pd.DataFrame):
        path = Path(gdp)
        if not path.exists():
            raise FileNotFoundError(f"GDP file not found: {path}")
        table = pd.read_excel(path) if path.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(path)
    cols = {c.lower(): c for c in table.columns}
    country = next((cols[c] for c in cols if "country" in c), None)
    year = next((cols[c] for c in cols if c in ("year", "yr") or "year" in c), None)
    others = [c for c in table.columns if c not in (country, year) and pd.api.types.is_numeric_dtype(table[c])]
    if country is None or year is None or not others:
        raise ValueError(
            "The GDP file needs a country column, a year column and one numeric GDP column "
            f"(e.g. Country, Year, GDP). Columns found: {list(table.columns)}"
        )
    return _aggregate.monthly_gdp(table, country_col=country, year_col=year, value_col=others[0], end=end,
                                  aliases=dict(names or {}))


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class IndexResult:
    """Everything one :func:`build_index` call produced.

    ``country``     -- the country index (one row per country and month; the
                       value column is named after the index: EPU, TPU, ...).
                       With ``history``, this is the version scored against
                       the history period.
    ``no_history``  -- with ``history``: the same months scaled on
                       ``start``..``end`` only, to compare or use.
    ``wide`` / ``wide_no_history`` -- the same, one column per country
    ``groups`` / ``groups_no_history`` -- GDP-weighted index for each block of
                       countries (only if ``gdp`` was given)
    ``history``     -- the fixed scaling taken from the history period (only
                       if ``history`` was given); ``files=[..., "history"]`` saves it
    ``counts``      -- articles and matching articles per newspaper and month
    ``keywords``    -- the exact keywords used (country, group, term)
    ``skipped_files`` -- article files that could not be read (if any)

    ``show``, ``plot``, ``table`` and ``save`` take ``version="history"``,
    ``"no history"`` or ``"both"`` (the default shows/saves everything there is).
    """

    country: pd.DataFrame
    counts: pd.DataFrame
    settings: dict
    groups: pd.DataFrame | None = None
    history: _index.History | None = None  # the fixed scaling from the history period
    no_history: pd.DataFrame | None = None
    groups_no_history: pd.DataFrame | None = None
    keywords: pd.DataFrame = field(default_factory=pd.DataFrame)
    skipped_files: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def measure(self) -> str:
        """The index name and value column: "EPU", "TPU", ..."""
        return self.settings.get("index", "EPU")

    @property
    def prefix(self) -> str:
        return self.measure.lower()

    # -- which versions exist ---------------------------------------------------
    def _versions(self, version: str = "both") -> list[tuple[str, str, pd.DataFrame, pd.DataFrame | None]]:
        """[(key, label, country table, group table)] for the requested version(s)."""
        key = str(version).strip().lower().replace("_", " ").replace("-", " ")
        if key not in ("both", "all", "history", "with history", "no history", "without history"):
            raise ValueError('version must be "history", "no history" or "both".')
        period = self.settings["period"]
        if self.history is None:  # only one version exists
            if key in ("history", "with history"):
                raise ValueError("This result has no history version: run build_index with history=(start, end).")
            return [("no_history", f"no history (scaled on {period})", self.country, self.groups)]
        out = []
        if key in ("both", "all", "history", "with history"):
            out.append(("history", f"with history {self.history.start}..{self.history.end}",
                        self.country, self.groups))
        if key in ("both", "all", "no history", "without history"):
            out.append(("no_history", f"no history (scaled on {period})", self.no_history,
                        self.groups_no_history))
        return out

    def _wide(self, table: pd.DataFrame) -> pd.DataFrame:
        if table is None or table.empty:
            return pd.DataFrame()
        wide = table.pivot(index="year_month", columns="country", values=self.measure)
        wide.columns.name = None
        return wide.round(2)

    @property
    def wide(self) -> pd.DataFrame:
        return self._wide(self.country)

    @property
    def wide_no_history(self) -> pd.DataFrame:
        return self._wide(self.no_history if self.history is not None else self.country)

    def table(self, version: str = "both") -> pd.DataFrame:
        """One row per country (and version): months, latest value, average, highest month."""
        rows = []
        versions = self._versions(version)
        for _key, label, data, _groups in versions:
            for name, g in data.groupby("country", sort=True):
                g = g.sort_values("year_month")
                v = self.measure
                peak = g.loc[g[v].idxmax()]
                row = {"country": name}
                if len(versions) > 1:
                    row["version"] = label.split(" (")[0]
                row.update({
                    "months": len(g),
                    "from": g["year_month"].iloc[0],
                    "to": g["year_month"].iloc[-1],
                    f"latest {v}": round(float(g[v].iloc[-1]), 1),
                    "average": round(float(g[v].mean()), 1),
                    "highest": round(float(peak[v]), 1),
                    "highest in": peak["year_month"],
                })
                rows.append(row)
        table = pd.DataFrame(rows)
        return table.sort_values(["country"], kind="stable").reset_index(drop=True) if len(table) else table

    def show(self, months: int = 6, version: str = "both") -> None:
        """Print a short summary and the latest ``months`` of the index, for one or both versions."""
        print(f"{self.measure} index | {self.settings['period']} | {', '.join(self.settings['countries'])}")
        for _key, label, data, group_table in self._versions(version):
            print(f"\n=== {label.upper()} ===")
            if data is None or data.empty:
                print("No index values: no newspaper had enough months to be scaled.")
                continue
            print(self.table(_key.replace("_", " ")).to_string(index=False))
            print(f"\nLast {months} months:")
            print(self._wide(data).tail(months).to_string())
            if group_table is not None and group_table.empty:
                print(f"\nGroup {self.measure}: none (each country needs 2+ months with a changing index in the scaling period).")
            elif group_table is not None:
                latest = group_table.sort_values("year_month").groupby("group").tail(1)
                print(f"\nGroup {self.measure} (latest month):")
                print(latest[["group", "year_month", "index", "n_countries"]].round(1).to_string(index=False))
        if len(self.skipped_files):
            print(f"\nNote: {len(self.skipped_files)} article file(s) could not be read and were skipped "
                  "(see result.skipped_files).")

    def plot(self, version: str = "both", path: str | Path | None = None):
        """Line chart, one colour per country. With ``version="both"``: solid =
        with history, dashed = no history. Saves it too if ``path`` is given."""
        import matplotlib.pyplot as plt

        versions = self._versions(version)
        fig, ax = plt.subplots(figsize=(10, 5))
        colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
        countries = sorted(set().union(*[set(d["country"]) for _k, _l, d, _r in versions if d is not None]))
        for i, name in enumerate(countries):
            for j, (_key, label, data, _groups) in enumerate(versions):
                g = data[data["country"] == name].sort_values("year_month")
                if g.empty:
                    continue
                tag = f"{name}" + (f" ({label.split(' (')[0]})" if len(versions) > 1 else "")
                ax.plot(pd.PeriodIndex(g["year_month"], freq="M").to_timestamp(), g[self.measure],
                        color=colors[i % len(colors)], linestyle="-" if j == 0 else "--", label=tag)
        import matplotlib.dates as mdates

        locator = mdates.AutoDateLocator(minticks=3, maxticks=10)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.axhline(100, color="grey", linewidth=0.8, linestyle=":")
        ax.set_ylabel(f"{self.measure} index")
        ax.set_title(f"{self.settings.get('title', self.measure)}, {self.settings['period']}")
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        if path is not None:
            fig.savefig(path, dpi=150, bbox_inches="tight")
        return fig

    #: What :meth:`save` can write; the default is the first two.
    FILES = ("dashboard", "excel", "csv", "chart", "history")

    def dashboard(self, path: str | Path | None = None, months: int = 12, version: str = "both",
                  title: str | None = None) -> Path:
        """Write the HTML dashboard (charts, tables, newspapers, keywords) and return its path.

        ``title`` sets the heading, e.g. ``"Africa Economic Policy Uncertainty Index -- October 2026"``;
        default: the title given to :func:`build_index`, or an automatic one.
        """
        from .dashboard import write

        path = path if path is not None else f"{self.prefix}_dashboard.html"
        out = write(self, output_folder(path), months=months, version=version, title=title)
        print(f"Dashboard saved: {out.resolve()}")
        return out

    def save(
        self,
        folder: str | Path | None = None,
        files: str | list[str] | tuple[str, ...] = ("dashboard", "excel"),
        version: str = "both",
        title: str | None = None,
    ) -> Path:
        """Save the results to ``folder``.

        A relative folder such as ``"my_results"`` is created next to the
        script you are running (in Jupyter: next to the notebook); a full path
        like ``r"C:\\EPU\\results"`` is used as given. ``title`` sets the
        dashboard heading (default: the title given to :func:`build_index`).

        ``files`` -- what to write (default: dashboard + Excel):
          ``"dashboard"`` one HTML page with every chart and table (opens in any browser)
          ``"excel"``     one workbook, one sheet per table
          ``"csv"``       the same tables as separate CSV files
          ``"chart"``     the main chart as a PNG image
        ``"all"`` writes all four. ``version``: ``"history"``, ``"no history"``
        or ``"both"``. ``"history"`` also writes ``history.json`` (the fixed
        scaling) so a later run can reuse it exactly via ``history=``.
        """
        choice = [f for f in self.FILES if f != "history"] if files == "all" else ([files] if isinstance(files, str) else list(files))
        unknown = [f for f in choice if f not in self.FILES]
        if unknown:
            raise ValueError(f"files can be {', '.join(map(repr, self.FILES))} or 'all' (got {unknown}).")
        out = output_folder(folder if folder is not None else f"{self.prefix}_results")
        out.mkdir(parents=True, exist_ok=True)
        pre = self.prefix
        written: list[str] = []
        versions = self._versions(version)

        tables = {"summary": self.table(version)}
        for key, _label, data, group_table in versions:
            tables[f"{pre}_{key}"] = self._wide(data)
            tables[f"{pre}_{key}_long"] = data
            if group_table is not None:
                tables[f"groups_{key}"] = group_table
        tables["newspaper_counts"] = self.counts
        tables["keywords_used"] = self.keywords
        if len(self.skipped_files):
            tables["skipped_files"] = self.skipped_files

        if "dashboard" in choice:
            from .dashboard import write

            write(self, out / f"{pre}_dashboard.html", version=version, title=title)
            written.append(f"{pre}_dashboard.html")
        if "excel" in choice:
            try:
                with pd.ExcelWriter(out / f"{pre}_results.xlsx") as xl:
                    for name, table in tables.items():
                        wide = name.startswith(f"{pre}_") and not name.endswith("_long")
                        table.to_excel(xl, sheet_name=name[:31], index=wide)
                written.append(f"{pre}_results.xlsx")
            except ImportError:
                print("Excel needs openpyxl (pip install openpyxl); writing CSV files instead.")
                choice.append("csv")
        if "csv" in choice:
            for name, table in tables.items():
                wide = name.startswith(f"{pre}_") and not name.endswith("_long")
                table.to_csv(out / f"{name}.csv", index=wide, encoding="utf-8-sig")
                written.append(f"{name}.csv")
        if "chart" in choice:
            try:
                import matplotlib

                matplotlib.use("Agg", force=False)
                import matplotlib.pyplot as plt

                plt.close(self.plot(version, out / f"{pre}_chart.png"))
                written.append(f"{pre}_chart.png")
            except ImportError:
                print("The chart needs matplotlib (pip install CAPEnewsindex[plot]).")
        if "history" in choice and self.history is not None:
            self.history.save(out / "history.json")
            written.append("history.json")
        print(f"Saved to {out.resolve()}:")
        for name in dict.fromkeys(written):
            print(f"  {name}")
        return out

    def __repr__(self) -> str:
        n = self.country["country"].nunique() if len(self.country) else 0
        versions = " + no history" if self.history is not None else ""
        return (f"<IndexResult: {n} countr{'y' if n == 1 else 'ies'}, {self.settings['period']}, "
                f"{self.settings['mode']}{versions} -- use .show(), .plot(), .save(folder)>")


# ---------------------------------------------------------------------------
# The one call
# ---------------------------------------------------------------------------
def build_index(
    archive: str | Path,
    keywords,
    countries: str | list[str] = "all",
    start: str | None = None,
    end: str | None = None,
    *,
    history: tuple[str, str] | str | Path | _index.History | None = None,
    index: list[str] | tuple[str, ...] = ("economic", "policy", "uncertainty"),
    name: str | None = None,
    gdp: str | Path | pd.DataFrame | None = None,
    gdp_names: dict[str, str] | None = None,
    groups: dict[str, list[str]] | None = None,
    title: str | None = None,
    output: str | Path | None = None,
    files: str | list[str] | tuple[str, ...] = ("dashboard", "excel"),
    workers: int | None = None,
    cache: bool = True,
    verbose: bool = True,
) -> IndexResult:
    """Build an EPU-type index (EPU, TPU, PU, or any 2+ keyword groups) from a
    scraped-article archive in one call.

    archive    -- the folder holding one sub-folder per country
                  (``<archive>/<country>/<newspaper>/<YYYY-MM>/articles_*.csv.gz``)
    keywords   -- your keywords, in the format you prefer: a ``.xlsx`` or
                  ``.csv`` sheet (columns country, group, term), a ``.txt``
                  file ([Country] sections, one term per line), a ``.json``
                  file, or a Python dict. ``ni.keywords_template("my_keywords.xlsx")``
                  (or .csv / .txt / .json) writes a template to start from.
    countries  -- one country (``"Nigeria"``), a list (``["Nigeria", "Ghana"]``),
                  or ``"all"`` (default). Upper/lower case doesn't matter.
    start, end -- first and last month, ``"YYYY-MM"``. Left out, they are the
                  first and the latest month found in the archive.
    index      -- the keyword groups an article must all contain, 2 or more:
                  ``["economic", "policy", "uncertainty"]`` (EPU, the default),
                  ``["trade", "policy", "uncertainty"]`` (TPU),
                  ``["policy", "uncertainty"]`` (PU), ... The groups must be in
                  your keyword file.
    name       -- your acronym for the index, e.g. ``"EgPU"``; it names the
                  value column, the files and the dashboard. Default: the
                  initials of the groups ("EPU", "TPU", "PU", ...).
    history    -- leave out for an index scaled on ``start``..``end`` itself
                  (no history). Give a history period, e.g.
                  ``("2015-01", "2024-12")``, to scale on that period and score
                  ``start``..``end`` against it -- you then get both versions;
                  or reuse a ``history.json`` saved with ``files=[..., "history"]``.
    gdp        -- your annual GDP file (CSV or Excel with country, year and GDP
                  columns). Needed for group indices: GDP-weighted indices for
                  blocks of countries (``result.groups``), with or without history.
    gdp_names  -- renames for countries spelled differently in the GDP file
                  than in the archive, e.g. ``{"Burkina Faso": "Burkina-Faso"}``.
                  Nothing is renamed unless you say so.
    groups     -- the blocks to build, any countries you like, e.g.
                  ``{"Euro area": ["Germany", "France"], "Nordics": ["Sweden", "Denmark"]}``.
                  A country may be in several blocks. Default (with ``gdp``):
                  one block of all countries in the run.
    title      -- the dashboard heading, e.g. "Africa Economic Policy Uncertainty Index".
                  Default: an automatic one ("EPU index (economic + policy + uncertainty) dashboard").
    output     -- a folder to save the results in straight away (relative
                  folders go next to your script). ``files`` picks what to
                  write there: "dashboard", "excel", "csv", "chart" or "all".
    workers    -- CPU cores to use; default all. ``cache`` (default on) keeps
                  each file's results so re-runs only read new files.

    Files that can't be read are skipped and listed in
    ``result.skipped_files`` instead of stopping the run.
    """
    t0 = time.perf_counter()

    # Anything left empty is simply skipped.
    def _empty(v) -> bool:
        if v is None:
            return True
        if isinstance(v, (str, Path)):
            return str(v).strip() == ""
        if isinstance(v, (list, tuple, dict, set)):
            return len(v) == 0
        if isinstance(v, pd.DataFrame):
            return v.empty
        return False

    history = None if _empty(history) else history
    gdp = None if _empty(gdp) else gdp
    groups = None if _empty(groups) else groups
    output = None if _empty(output) else output
    end = None if _empty(end) else end
    start = None if _empty(start) else start
    gdp_names = None if _empty(gdp_names) else gdp_names
    countries = "all" if _empty(countries) else countries
    files = ("dashboard", "excel") if _empty(files) else files
    if groups is not None and gdp is None:
        _say(verbose, "Note: groups need a GDP file (gdp=...), so the group index is skipped.")
        groups = None
    if groups is not None and (
        not isinstance(groups, dict) or not groups
        or not all(isinstance(v, (list, tuple)) and v for v in groups.values())
    ):
        raise ValueError('groups must be a dict of country lists, e.g. {"Euro area": ["Germany", "France"]}.')

    # --- check the inputs -------------------------------------------------
    for label, value in (("archive", archive), ("keywords", keywords), ("gdp", gdp)):
        if isinstance(value, tuple) and len(value) == 1 and isinstance(value[0], (str, Path)):
            raise TypeError(
                f"{label} is a tuple, not a path -- usually a stray comma at the end of the line, like\n"
                f"    {label} = r\"C:\\...\",\nRemove the comma after the closing quote."
            )
    archive = input_path(archive)
    keywords = input_path(keywords) if isinstance(keywords, (str, Path)) else keywords
    gdp = input_path(gdp)
    history = input_path(history) if isinstance(history, (str, Path)) else history
    if not archive.is_dir():
        raise FileNotFoundError(f"Archive folder not found: {archive}\nCheck the path (copy it from File Explorer).")
    name = None if _empty(name) else name
    measure, auto_title, required = _index_spec(index, name)
    kw = _dictionary.read(keywords)
    selected = _resolve(archive, countries, kw, required)
    kw = _for_countries(kw, selected, required)
    if start is None:
        start = _first_month(archive, selected)
        if start is None:
            raise FileNotFoundError(f"No YYYY-MM month folders found for {selected} under {archive}")
    start = _check_month(start, "start")
    if end is None:
        end = _latest_month(archive, selected)
        if end is None:
            raise FileNotFoundError(f"No YYYY-MM month folders found for {selected} under {archive}")
    end = _check_month(end, "end")
    # Read the GDP file now, so a wrong path fails in a second, not after the whole archive is read.
    weights = _read_gdp(gdp, end, gdp_names) if gdp is not None else None
    if start > end:
        raise ValueError(f"start ({start}) is after end ({end}).")

    fixed = None
    windows = [(start, end)]
    if isinstance(history, _index.History):
        fixed = history
    elif isinstance(history, (str, Path)) and str(history).lower().endswith(".json"):
        if not Path(history).exists():
            raise FileNotFoundError(f"History file not found: {history}")
        fixed = _index.History.load(history)
    elif history is not None:
        if not (isinstance(history, (tuple, list)) and len(history) == 2):
            raise ValueError('history must be a period like ("2015-01", "2024-12") or a saved history .json file.')
        b_start, b_end = (_check_month(history[0], "history start"), _check_month(history[1], "history end"))
        if b_start > b_end:
            raise ValueError(f"history start ({b_start}) is after history end ({b_end}).")
        windows.append((b_start, b_end))

    # The history months are also needed for group indices (to standardise each country).
    read_windows = list(windows)
    if fixed is not None and gdp is not None:
        read_windows.append((fixed.start, fixed.end))

    mode = "no history" if history is None else (
        f"history {fixed.start}..{fixed.end} (saved)" if fixed is not None else f"history {windows[1][0]}..{windows[1][1]}")
    _say(verbose, f"CAPEnewsindex {__version__} | {measure} | {len(selected)} countr{'y' if len(selected) == 1 else 'ies'} | "
                  f"{start}..{end} | {mode}")
    source = f" from {Path(kw.source).name}" if kw.source else ""
    _say(verbose, f"Keywords{source} ({' / '.join(required)}):")
    for c in selected:
        e = kw[c]
        sizes = " / ".join(f"{len(e.terms(g)):>4}" for g in required)
        examples = " | ".join(", ".join(e.terms(g)[:2]) for g in required)
        _say(verbose, f"  {c:<24} {sizes}   e.g. {examples}")
    _say(verbose, "Reading articles ...")

    # --- read and count -----------------------------------------------------
    skipped: list[dict] = []

    live = verbose and (sys.stdout.isatty() or "ipykernel" in sys.modules)
    last = {"t": 0.0, "shown": False}

    def file_progress(st: dict) -> None:
        if not verbose:
            return
        now, finished = time.perf_counter(), st["files_done"] == st["files_total"]
        if not finished and now - last["t"] < (0.5 if live else 30):  # a calm, steady update
            return
        last["t"] = now
        share = st["bytes_done"] / st["bytes_total"] if st["bytes_total"] else 1.0
        new = st["files_done"] - st["from_cache"]
        eta = ""
        if 0 < share < 1 and st["seconds"] > 3 and new > 0:
            eta = f" | about {_duration(st['seconds'] * (1 - share) / share)} left"
        line = (f"  {st['files_done']:,}/{st['files_total']:,} files ({share:.0%}) | "
                f"{st['articles']:,} articles | {_duration(st['seconds'])}{eta}")
        if live:
            print("\r" + line.ljust(90), end="", flush=True)
        else:
            print(line, flush=True)
        last["shown"] = True

    by_folder = count_archive_fast(
        archive, kw, countries=selected, windows=read_windows, workers=workers,
        cache=cache, skipped=skipped, by_folder=True, file_progress=file_progress, groups=required,
    )
    # One scan, several views -- each identical to a run that read only its own months.
    counts = collapse_folders(by_folder)
    counts_window = collapse_folders(by_folder, [(start, end)])
    if live and last["shown"]:
        print("\r" + " " * 90 + "\r", end="")

    # --- compute the index: always without history, and with it when asked ---------
    no_history = _index.compute_index(counts_window, start, end)
    country, scored_all = no_history, None
    if history is not None:
        if fixed is None:
            fresh = collapse_folders(by_folder, windows)  # what run_index_with_history reads
            fixed = _index.fit_history(fresh, windows[1][0], windows[1][1],
                                        dictionary_fingerprint=_dictionary.fingerprint(kw))
            scoring_counts = fresh
        else:
            if fixed.dictionary_fingerprint and fixed.dictionary_fingerprint != _dictionary.fingerprint(kw):
                _say(verbose, "  Note: this history was fitted with different keywords than the ones used now.")
            scoring_counts = counts_window
        country = _index.score(scoring_counts, fixed)
        country = country[(country["year_month"] >= start) & (country["year_month"] <= end)].reset_index(drop=True)
        scored_all = _index.score(counts, fixed)  # history months too (for group indices)

    for name in selected:
        c = counts_window[counts_window["country"] == name]
        e = country[country["country"] == name]
        _say(verbose, f"  {name:<24} {c['site'].nunique():>3} newspapers  {int(c['all_articles'].sum()):>10,} articles"
                      f"  {int(c['epu_articles'].sum()):>8,} {measure}  {len(e):>4} months")

    if skipped:
        _say(verbose, f"  Note: {len(skipped)} file(s) could not be read and were skipped (see result.skipped_files).")
    no_index = [c for c in selected if c not in set(country["country"])]
    if no_index:
        _say(verbose, f"  Note: no index for {', '.join(no_index)} -- no newspaper had 2+ months with a "
                      f"changing {measure} share in the scaling period"
                      + (" (some of their files could not be read: see result.skipped_files)." if skipped else "."))

    group_out = group_nb = None
    blocks: dict[str, list[str]] = {}
    no_gdp: list[str] = []
    if weights is not None:
        blocks, no_gdp = _blocks(groups, selected, set(weights["country"]), verbose)

        def _grouped(series, a, b):
            r = _aggregate.aggregate(series, weights, groups=blocks, value="EPU", history_start=a, history_end=b)
            return r[(r["year_month"] >= start) & (r["year_month"] <= end)].reset_index(drop=True)

        group_nb = _grouped(no_history, start, end)
        group_out = group_nb if fixed is None else _grouped(scored_all, fixed.start, fixed.end)

    both = " (with and without history)" if history is not None else ""
    hint = "  Next: result.show(), result.plot()" + ("" if output is not None else ', result.save("folder")')
    _say(verbose, f"Done in {time.perf_counter() - t0:,.1f}s{both}.{hint}")

    # Name everything after the index (EPU, TPU, ...) for the user.
    def named(table):
        return None if table is None else table.rename(columns={"EPU": measure})

    result = IndexResult(
        country=named(country),
        no_history=named(no_history) if history is not None else None,
        groups_no_history=group_nb if history is not None else None,
        counts=counts.rename(columns={"epu_articles": f"{measure.lower()}_articles"}),
        settings={"archive": str(archive), "countries": selected, "period": f"{start}..{end}", "mode": mode,
                  "index": measure, "title": auto_title, "keyword_groups": list(required),
                  "groups": blocks,           # members of each group index (countries with GDP only)
                  "no_gdp": no_gdp,           # countries without GDP: own index only, in no group
                  "dashboard_title": None if _empty(title) else str(title).strip()},
        groups=group_out,
        history=fixed,
        keywords=_dictionary.to_table(kw, groups=list(required)).reset_index(drop=True),
        skipped_files=pd.DataFrame(skipped, columns=["country", "year_month", "file", "error"]),
    )
    if output is not None:
        result.save(output, files=files)
    return result


def _duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    return f"{minutes}m {sec:02d}s" if minutes < 60 else f"{minutes // 60}h {minutes % 60:02d}m"


def output_folder(folder: str | Path) -> Path:
    """Where a results folder goes: a full path as given; a relative one
    (e.g. ``"my_results"``) next to the script being run -- not wherever the
    terminal happens to be. In Jupyter (no script) it is the notebook's folder."""
    path = Path(folder).expanduser()
    if path.is_absolute():
        return path
    main = sys.modules.get("__main__")
    script = getattr(main, "__file__", None)
    if script and "ipykernel" not in sys.modules:
        return Path(script).resolve().parent / path
    return Path.cwd() / path


def _blocks(groups, selected: list[str], with_gdp: set[str], verbose: bool):
    """The blocks to aggregate: your groups, limited to countries in this run that have GDP.
    Also returns the countries in this run without GDP (they keep their own index only)."""
    if groups is None:
        wanted = {"All countries": list(selected)}
    else:
        wanted = {str(k): [str(c) for c in v] for k, v in groups.items()}
    in_run = {c.lower(): c for c in selected}
    blocks: dict[str, list[str]] = {}
    not_in_run, no_gdp = set(), set()
    for name, members in wanted.items():
        kept = []
        for c in members:
            folder = in_run.get(c.strip().lower())
            if folder is None:
                not_in_run.add(c)
            elif folder not in with_gdp:
                no_gdp.add(folder)
            else:
                kept.append(folder)
        if kept:
            blocks[name] = kept
    no_gdp |= {c for c in selected if c not in with_gdp}
    if no_gdp:
        _say(verbose, f"  Note: no GDP for {', '.join(sorted(no_gdp))} -- left out of the group index.")
        unused = sorted(set(with_gdp) - set(selected))
        hints = {c: difflib.get_close_matches(c, unused, n=1, cutoff=0.6) for c in sorted(no_gdp)}
        hints = {c: m[0] for c, m in hints.items() if m}
        if hints:
            pairs = ", ".join(f'"{m}": "{c}"' for c, m in hints.items())
            _say(verbose, f"  The GDP file may spell them differently -- if so, add gdp_names={{{pairs}}}.")
    if not_in_run:
        _say(verbose, f"  Note: not in this run, so left out of the groups: {', '.join(sorted(not_in_run))}.")
    if not blocks:
        raise ValueError("None of the group countries are in this run with GDP data, so no group index can be built.")
    return blocks, sorted(no_gdp)


def input_path(value):
    """A relative input path is looked up where you are, then next to your script."""
    if not isinstance(value, (str, Path)):
        return value
    path = Path(value).expanduser()
    if path.is_absolute() or path.exists():
        return path
    beside_script = output_folder(path)
    return beside_script if beside_script.exists() else path


def _first_month(archive: Path, countries: list[str]) -> str | None:
    first = None
    for c in countries:
        for site in (archive / c).iterdir():
            if site.is_dir():
                months = [m.name for m in site.iterdir() if m.is_dir() and _MONTH.match(m.name)]
                if months and (first is None or min(months) < first):
                    first = min(months)
    return first


def _latest_month(archive: Path, countries: list[str]) -> str | None:
    latest = None
    for c in countries:
        for site in (archive / c).iterdir():
            if site.is_dir():
                months = [m.name for m in site.iterdir() if m.is_dir() and _MONTH.match(m.name)]
                if months and (latest is None or max(months) > latest):
                    latest = max(months)
    return latest
