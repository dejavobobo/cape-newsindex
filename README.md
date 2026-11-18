# CAPEnewsindex

[![PyPI](https://img.shields.io/pypi/v/CAPEnewsindex.svg)](https://pypi.org/project/CAPEnewsindex/)
[![Python](https://img.shields.io/pypi/pyversions/CAPEnewsindex.svg)](https://pypi.org/project/CAPEnewsindex/)
[![tests](https://github.com/CAPE-ERC/cape-newsindex/actions/workflows/tests.yml/badge.svg)](https://github.com/CAPE-ERC/cape-newsindex/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Build news-based uncertainty indices (EPU, TPU, or any index you define from two or more keyword groups) from newspaper archives, for any country and language, using the Baker, Bloom and Davis (2016) method.

You supply the articles, the keywords and, for group indices, the GDP. One call gives you:
- country indices with and without a history period;
- GDP-weighted indices for groups of countries you define;
- an HTML dashboard and an Excel workbook.

Files are read in parallel and cached, so re-runs take seconds.

Developed by **CAPE Economic Research and Consulting**.

**Contents:** [Install](#install) · [Quick start](#quick-start) · [What you need](#what-you-need) · [Use cases](#use-cases) · [More tools](#more-tools) · [Reference](#reference) · [Development](#development) · [Citation](#citation)

---

## Install

```bash
pip install "CAPEnewsindex[plot,excel]"          # Python 3.10+
```

| Extra | Adds |
| --- | --- |
| `plot` | charts (`result.plot()`, PNG export, chart functions) |
| `excel` | the Excel workbook |
| `plotly`, `seaborn`, `parquet`, `gsheet`, `docx`, `pdf` | other chart styles and file formats |

The HTML dashboard needs no extra.

## Quick start

```python
import CAPEnewsindex as ni

result = ni.build_index(
    archive   = r"C:\data\Scrapped_Top_Articles",
    keywords  = "my_keywords.xlsx",
    countries = ["Nigeria", "Ghana"],
    history   = ("2015-01", "2025-12"),
    output    = "my_results",            # epu_dashboard.html + epu_results.xlsx
)
result.show()
```

## What you need

| Input | Form |
| --- | --- |
| **Archive** | `<archive>/<country>/<newspaper>/<YYYY-MM>/*.csv(.gz)`, columns `site, date, title, url, text`. Folder names are the country names used everywhere. |
| **Keywords** (required) | `.xlsx`/`.csv` (columns `country, group, term`), `.txt` (`[Country]`, then `group:` lines, one term per line), `.json`, or a dict. A country `*` applies to every country. |
| **GDP** (only for group indices) | CSV/Excel or DataFrame, **annual** (`2015`), **quarterly** (`2015Q1`) or **monthly** (`201501`, `2015-01`): a country, a period and a GDP column, or a period column plus one column per country. Turned into months (log-linear). See [GDP: annual, quarterly or monthly](#gdp-annual-quarterly-or-monthly). |

---

## Use cases

Every setting you leave empty (`None`, `""`, `[]`, `{}`) is skipped.

**1. One country, or several, or all.**
```python
ni.build_index(archive, keywords, "Nigeria", "2024-01", "2026-10")
ni.build_index(archive, keywords, ["Nigeria", "Ghana"], "2024-01")      # end = latest month
ni.build_index(archive, keywords, "all")                                # every country, every month
```
Names are checked against the folders (typos get a suggestion). Left out, `start` and `end` are the first and latest months in the archive.

**2. No history** (scaled on `start`..`end`, so 100 = that window's average). Use this for exploring.
```python
ni.build_index(archive, keywords, ["Nigeria", "Ghana"], "2024-01", "2026-10")
```

**3. With history** (100 = the history-period average; past values never change). Use this for publishing.
```python
result = ni.build_index(archive, keywords, ["Nigeria", "Ghana"], "2015-01", "2026-10",
                        history=("2015-01", "2025-12"))
```
You get both versions; pick one with `version="history"`, `"no history"` or `"both"` in `show`, `plot` and `save`.

**4. Any index.** Pass two or more keyword groups, plus an optional acronym:
```python
index=["economic", "policy", "uncertainty"]                 # EPU (default)
index=["trade", "policy", "uncertainty"]                    # TPU
index=["energy", "policy", "uncertainty"], name="EgPU"
index=["policy", "uncertainty"]                             # PU
index=["economic", "policy", "uncertainty", "value_chain"]  # EPUV
```
An article counts when it has a term from every group. The name labels the columns, the files and the dashboard (`tpu_dashboard.html`).

**5. Group indices** (GDP-weighted), for groups you define on any continent:
```python
regions = {
    "West":  ["Nigeria", "Ghana", "Senegal"],
    "East":  ["Kenya", "Ethiopia"],
    "North": ["Egypt", "Morocco"],
}
regions["Africa"] = sorted(c for m in regions.values() for c in m)     # whole continent
result = ni.build_index(archive, keywords, "all", "2015-01", "2026-10", history=("2015-01", "2025-12"),
                        gdp="my_gdp.csv", groups=regions)
result.groups, result.groups_no_history
```
- **No built-in regions.** Without `groups`, all countries form one group.
- **Only countries with GDP** are in a group. The others keep their own index and are listed separately on the dashboard.
- **GDP may be annual, quarterly or monthly.** The frequency is read from the file and printed, e.g. `GDP: quarterly, 2015Q1..2025Q4, 54 countries`. To state it, add `gdp_frequency="quarterly"` (or `"annual"`, `"monthly"`). Details are [below](#gdp-annual-quarterly-or-monthly).
- **`ni.countries()`** (an ISO table with UN regions) helps build groups.

**6. GDP names that differ from your folders.**
```python
gdp_names={"Burkina Faso": "Burkina-Faso", "Cabo Verde": "Cape Verde"}   # GDP-file name: folder name
```
Nothing is renamed otherwise. The run suggests this line when it finds a similar name.

**7. Keywords from the template.** The bundled CAPE dictionary covers 54 African countries; it is only used if you write it out.
```python
ni.keywords_template("my_keywords.xlsx", countries=["Nigeria", "Ghana"])        # or .csv / .txt / .json
ni.dictionary.validate(ni.dictionary.read("my_keywords.xlsx"))                  # empty groups, overlaps
ni.dictionary.save_keywords(ni.dictionary.read("my_keywords.xlsx"), "kw.json")  # convert format
```

**8. Monthly update.** Option A: keep the same `history=` and move `end`. Option B is faster on a cloud drive: save the scaling once, then reuse it.
```python
ni.build_index(..., history=("2015-01", "2025-12"), files=["dashboard", "excel", "history"], output="EPU_base")
ni.build_index(archive, keywords, countries, "2026-11", "2026-11", history="EPU_base/history.json",
               output="EPU_2026_11")
```
Both give exactly the same values as a full run. Keep the same keywords when reusing `history.json`.

**9. Look at the results.**
```python
result.show(months=12, version="history"); result.plot(); result.table()
result.country, result.no_history, result.wide, result.groups, result.counts, result.keywords, result.skipped_files
```

**10. Save.**
```python
result.save("out")                                        # dashboard + Excel
result.save("out", files="all")                           # + CSV + PNG chart
result.save("out", files=["dashboard", "excel", "history"], version="history")
result.dashboard("epu.html", title="Africa EPU Index -- October 2026")   # or title= in build_index
```
Relative folders are created next to your script.

**11. Speed and output.** `workers=4` (default: all cores); `cache=False` (re-read everything); `verbose=False` (no printing).

---

## More tools

These all work on any result table. Your index column (`EPU`, `TPU`, ...) is found automatically.

```python
# Check data before a long run
ni.coverage(archive); ni.validate_archive(archive); ni.health_check(archive, "my_keywords.xlsx")
ni.dictionary_coverage(ni.dictionary.read("my_keywords.xlsx"), archive)

# Summaries and transformations
t = result.country
ni.summarize(t); ni.describe(t); ni.top(t, 5); ni.print_period(t, "2026-01", "2026-10")
ni.resample(t, "Q"); ni.rebase(t, ("2020-01", "2020-12")); ni.smooth(t, 3)

# Charts (matplotlib; backend="plotly" or "seaborn")
ni.plot(t); ni.plot_compare(t, countries=["Nigeria", "Ghana"]); ni.plot_regions(result.groups)
ni.plot_heatmap(t); ni.plot_rank(t, "2026-10"); ni.plot_rolling(t, 3); ni.plot_distribution(t, kind="box")
ni.plot_components(result.counts); ni.plot_history(result.history); ni.plot_dashboard(t)
ni.plot_correlation(t.query("country == 'Nigeria'"), series)   # series indexed by "YYYY-MM"
ni.save_plot(fig, "chart.png"); ni.theme("default")

# Reports and files
ni.report(t, "report.html"); ni.save_report(t, "report.docx")          # .html .md .docx .pdf
ni.save(t, "epu.csv"); ni.save_excel(t, "epu.xlsx", sheet_by="country"); ni.load("epu.csv")
ni.save_all({"country": t, "groups": result.groups}, "out", formats=("csv", "xlsx"))
ni.save_versioned(t, "runs", base_name="epu"); ni.save_sql(t, conn, "epu"); ni.save_gsheet(t, url)

# DataFrame versions of build_index (EPU groups)
t = ni.run_index(archive, keywords, "2024-01", "2026-10", countries=["Nigeria"])
t, history = ni.run_index_with_history(archive, keywords, windows=[("2026-01", "2026-10")],
                                       history_start="2015-01", history_end="2025-12")

# Building blocks
kw      = ni.dictionary.read("my_keywords.xlsx")
counts  = ni.index.count_archive(archive, kw, groups=("trade", "policy", "uncertainty"))
history = ni.index.fit_history(counts, "2015-01", "2025-12"); scored = ni.index.score(counts, history)
gdp_w   = ni.weights.gdp("my_gdp.csv", value_col="GDP", aliases={"Burkina Faso": "Burkina-Faso"})
ni.aggregate.aggregate(scored, gdp_w, groups=regions, history=history)    # also weights.equal / population / pca
articles = ni.read_articles(archive, countries=["Ghana"]); ni.dedup.dedupe(articles); ni.index.count(articles, kw)
```

---

## Reference

### `build_index` settings

| Setting | Meaning | Default |
| --- | --- | --- |
| `archive`, `keywords` | archive folder; keyword file or dict | required |
| `countries` | a name, a list, or `"all"` | `"all"` |
| `start`, `end` | `"YYYY-MM"` | first / latest month in the archive |
| `history` | `("YYYY-MM", "YYYY-MM")` or a `history.json` | none (no history only) |
| `index`, `name` | 2+ keyword groups; your acronym | EPU groups; initials |
| `gdp`, `gdp_names` | GDP file or DataFrame (annual, quarterly or monthly); name renames | none |
| `gdp_frequency` | `"auto"`, `"annual"`, `"quarterly"` or `"monthly"` | `"auto"` (read from the periods) |
| `groups` | `{"Group": [countries]}` (needs `gdp`) | one group of all countries |
| `title` | dashboard heading | automatic |
| `output`, `files` | folder; any of `dashboard`, `excel`, `csv`, `chart`, `history`, `all` | none; dashboard + Excel |
| `workers`, `cache`, `verbose` | cores; reuse cached file results; print progress | all; `True`; `True` |

### Outputs

**`{name}_dashboard.html`** is one self-contained page that opens offline. Its pages are:
- **Overview**: latest values, rankings and a summary;
- **Groups**: one chart per group;
- **Countries**: one chart per country, under your groups, with a search box;
- **Newspapers**: article counts;
- **Keywords**: every term used;
- **About**: the method, the settings and any files that couldn't be read.

A switch flips every page between *with history* and *no history*.

**`{name}_results.xlsx`** has every table, one per sheet.

### Method

1. **Classify.** An article counts when its title or text has a term from every keyword group. Terms match as whole words or phrases, ignoring case. Duplicates are removed per country and month, by canonical URL or by title and text.
2. **Share.** `S_it` = matching articles / all articles, for newspaper *i* in month *t*.
3. **Standardise.** `N_it = S_it / σ_i`, where `σ_i` is the newspaper's standard deviation over the scaling period (the history period, or `start`..`end`).
4. **Index.** `index_t = 100 · M_t / μ`, where `M_t` is the mean of `N_it` across newspapers and `μ` is the mean of `M_t` over the scaling period.
5. **Group index.** Each country's index becomes a z-score over the scaling period. The group is the GDP-weighted average of those z-scores, shown as 100 + 10 × the standardised value. The weights are each country's share of the group's GDP in that month: annual or quarterly GDP is first turned into months (see the next section).

Reference: Baker, Bloom and Davis (2016), *Quarterly Journal of Economics* 131(4), 1593–1636.

### GDP: annual, quarterly or monthly

The group indices weight countries by GDP, and the weights change every month. You can give GDP at any of three frequencies. The same rules apply to `ni.aggregate.monthly_gdp`, `ni.weights.gdp` and `ni.weights.population`.

**Layouts.** Columns are found by their names; upper or lower case and spaces don't matter.

| Layout | Example columns | Notes |
| --- | --- | --- |
| Long, one period column | `Country, Year, GDP` / `Country, Quarter, GDP` / `Country, Month, GDP` / `Country, Date, GDP` | a period column named year, quarter, month, date, period, time or year_month |
| Long, year plus a part | `Country, Year, Quarter, GDP` / `Country, Year, Month, GDP` | Quarter holds 1–4 or Q1; Month holds 1–12 or Jan |
| Wide | `date, Algeria, Angola, ...` | a period column and one numeric column per country, e.g. a monthly GDP sheet |

- **Country column:** a column named country (or containing "country"). A file with no such column is read as wide.
- **GDP column:** the numeric column whose name contains "gdp"; otherwise the first numeric column. For `weights.population`, the column with "pop" in its name.
- **Unusual names:** give them yourself with `ni.aggregate.monthly_gdp(path, country_col="Nation", period_col="Qtr", value_col="Real_GDP")`. `year_col` still works and means the same as `period_col`.

**Period labels.**

| Frequency | Accepted labels |
| --- | --- |
| Annual | `2015` (also `2015.0` from Excel) |
| Quarterly | `2015Q1`, `2015-Q1`, `2015 Q1`, `2015q1`, `Q1 2015`; or Year + Quarter columns |
| Monthly | `201501`, `2015-01`, `2015/01`, `2015M01`, `01/2015`, `Jan 2015`, `January 2015`; or Year + Month columns |
| Full dates | `2015-01-01`, `2015-03-31`, `1/1/2015`, or Excel dates |

- **Frequency from the labels:** with `gdp_frequency="auto"` (the default), it comes from the labels.
- **Full dates:** these go by their spacing. Dates 12 months apart are annual, 3 months apart quarterly, 1 month apart monthly. A date belongs to its own year, quarter or month, so `2015-03-31` is 2015Q1.
- **Month-first dates:** `1/4/2015` is read month-first, as 4 January 2015. Use ISO dates (`2015-04-01`) to avoid doubt.
- **Stating the frequency:** `gdp_frequency="annual"`, `"quarterly"` or `"monthly"` states it. Full dates are then placed in that period, and labels of another frequency stop the run with a message.

**From periods to months.** Each value is placed at the first month of its period, then grows at a constant monthly rate (linearly in logarithms) until it reaches the next period's value:

| Frequency | Value placed at | Between two values | After the last value |
| --- | --- | --- | --- |
| Annual | January of the year | log-linear over the 12 months to next January | held flat to December, then to `end` |
| Quarterly | January, April, July or October | log-linear over the 3 months to the next quarter | held flat to the quarter's last month, then to `end` |
| Monthly | the month itself | missing months filled log-linearly | held flat to `end` |

Example: Q1 = 100 and Q2 = 200 give January 100, February 126, March 159 and April 200.

- **Gaps:** a missing year, quarter or month is bridged the same way, with no hole.
- **Before a country's first value:** those months get no GDP, so the country is left out of its groups in those months.
- **Zero or negative values:** they are held flat instead of interpolated.
- **Repeated rows:** the same period twice with the same value is fine. Two different values for one period stop the run.

**Units and adjustment.**

- **Units:** only each country's share of the group's GDP matters, so billions vs millions, or a quarter's GDP vs an annual rate, doesn't change the index. That holds as long as every country uses the same units and frequency.
- **One frequency per file:** a file that mixes frequencies (for example `2015` and `2016Q1`) stops the run with a message. Convert the annual rows first, or keep one frequency.
- **Seasonal adjustment:** quarterly or monthly GDP should be seasonally adjusted, or annualised. Otherwise seasonal swings move the weights from quarter to quarter.

**Seeing what was used.**

- **The run prints it,** e.g. `GDP: quarterly, 2015Q1..2025Q4, 54 countries -- each quarter's value at its first month, log-linear to the next quarter; last value held flat to 2026-10`.
- **`result.settings`** holds `gdp_frequency` and `gdp_periods`.
- **Directly:**

```python
monthly = ni.aggregate.monthly_gdp("gdp_quarterly.csv", end="2026-10")   # country, year_month, gdp
monthly.attrs["frequency"], monthly.attrs["periods"]                    # 'quarterly', ('2015Q1', '2025Q4')
ni.build_index(archive, keywords, "all", gdp="gdp_ppp_monthly_wide.csv", gdp_frequency="monthly", groups=regions)
```

### Troubleshooting

| Message | Fix |
| --- | --- |
| `archive is a tuple, not a path` | remove the comma after `archive = "..."` |
| `no folder with this name ... Did you mean` | use the archive's folder name |
| `no energy keywords` | add that group for every country in the run |
| `keywords are required` | pass a keyword file or dict (`ni.keywords_template()` writes one) |
| `groups must be a dict of country lists` | `groups={"West": ["Nigeria", "Ghana"]}` |
| `no GDP for ...` | add the country to the GDP file, or map its spelling with `gdp_names=` |
| `Can't read these periods` | use a label from [the table](#gdp-annual-quarterly-or-monthly), e.g. `2015`, `2015Q1`, `2015-01` |
| `The GDP file mixes frequencies` | use one frequency (annual, quarterly or monthly) for every row |
| `frequency="..." but the periods look ...` | fix `gdp_frequency=`, or leave it `"auto"` |
| `Can't tell the frequency from a single date` | add `gdp_frequency="annual"` (or quarterly / monthly) |
| `Two different values for ... in the same quarter` | keep one row per country and period |
| `No country column found` | name it with `country_col=`, or use a wide file |
| all values near 100 in a short run | that is the no-history version: use `history=` |
| a run is much slower than usual | usually a cloud drive syncing: make the folder available offline, or use use case 8, option B |

---

## Development

### Set up

```bash
git clone https://github.com/CAPE-ERC/cape-newsindex.git
cd cape-newsindex
python -m pip install -e ".[test,plot,excel]"
python -m pytest                    # the whole suite; e.g. python -m pytest tests/test_simple.py -k groups
```

### Layout

```
src/CAPEnewsindex/
  simple.py       build_index and IndexResult (the main API)
  dashboard.py    the HTML dashboard (data embedded, charts drawn in plain JavaScript)
  fastscan.py     parallel archive reader and SQLite cache
  match.py        normalisation and whole-word/phrase matching
  dictionary.py   keyword files in every format; the bundled template
  index.py        counts, history scaling, scoring; value_column()
  aggregate.py    z-scores and group indices; weights.py (GDP, population, equal, PCA)
  pipeline.py     run_index, run_index_with_history
  diagnostics.py, report.py, plot.py, save.py, countries.py, dedup.py, articles.py
  _anyindex.py    lets the report/plot helpers work with any index name
  data/           keyword template, ISO country table, logo
tests/            pytest suite; tests/data/ holds a GDP file used only by the tests
examples/         run_epu.py, test_with_drive.ipynb, sample_articles.xlsx + test_with_excel.ipynb
```

### Rules for changes

- **Add or update a test with every change.** The fast reader is checked against a plain pandas implementation on randomized messy archives (`tests/test_fastscan.py`), so any change to reading or matching must keep that test passing.
- **Keep the library neutral.** No built-in countries, regions or data. Defaults must never pick keywords, groups or GDP for the user.
- **New settings follow the same rule:** empty means skipped.

### Continuous integration

`.github/workflows/tests.yml` runs the suite on Ubuntu and Windows with Python 3.10, 3.12, 3.13 and 3.14 for every push to `main` and every pull request.

### Release

1. Set the same version in `pyproject.toml` and `src/CAPEnewsindex/_version.py`. Use a new minor version when the API changes.
2. Commit and push, then tag: `git tag vX.Y.Z && git push origin vX.Y.Z`. The tag publishes to **TestPyPI**.
3. Check the TestPyPI install, then publish a **GitHub Release** for the tag. The release publishes to **PyPI**.

---

## Citation

```
CAPE Economic Research and Consulting. CAPEnewsindex: news-based uncertainty indices from
newspaper archives. https://github.com/CAPE-ERC/cape-newsindex

Baker, S. R., Bloom, N. and Davis, S. J. (2016). Measuring Economic Policy Uncertainty.
Quarterly Journal of Economics, 131(4), 1593–1636.
```

MIT License · © CAPE Economic Research and Consulting
