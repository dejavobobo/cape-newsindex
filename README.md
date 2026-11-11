# CAPEnewsindex

[![PyPI](https://img.shields.io/pypi/v/CAPEnewsindex.svg)](https://pypi.org/project/CAPEnewsindex/)
[![Python](https://img.shields.io/pypi/pyversions/CAPEnewsindex.svg)](https://pypi.org/project/CAPEnewsindex/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Build news-based uncertainty indices from newspaper archives, fast.** CAPEnewsindex builds an Economic Policy Uncertainty (EPU) index, or any index you define from two or more keyword groups (TPU, ETU, PU, EPUV, ...), for any country and any language. It uses the Baker, Bloom and Davis (2016) method.

You bring the scraped articles and your own keywords. In one call, CAPEnewsindex gives you:

- a monthly index for every country, **with and without a history period**, from a single read of the archive;
- **GDP-weighted indices** for the five African regions and Africa as a whole, or for **any blocks of countries you define** on any continent;
- one **HTML dashboard** with every chart and table, plus an **Excel workbook**, ready to share.

It is built for large archives. Files are read in parallel on every CPU core, and results are cached, so a re-run reads only new or changed files.

Developed by **CAPE Economic Research and Consulting**.

---

## Contents

**Getting started**
- [Install](#install)
- [Quick start](#quick-start)
- [What you need](#what-you-need): archive, keywords, GDP

**Use cases with `build_index`** (the one call most users need)

| # | Use case |
| --- | --- |
| [1](#1-one-country) | One country |
| [2](#2-several-countries-or-all-of-them) | Several countries, or all of them |
| [3](#3-no-history-quick-exploration) | No history: quick exploration |
| [4](#4-with-history-the-version-to-publish) | With history: the version to publish |
| [5](#5-other-indices-tpu-etu-pu-egpu-epuv-) | Other indices: TPU, ETU, PU, EgPU, EPUV, ... |
| [6](#6-group-index-all-countries-together) | Group index: all countries together |
| [7](#7-african-regions-and-africa-as-a-whole) | African regions and Africa as a whole |
| [8](#8-your-own-blocks-of-countries-any-continent) | Your own blocks of countries, any continent |
| [9](#9-keywords-start-from-the-template-or-write-your-own) | Keywords: start from the template, or write your own |
| [10](#10-monthly-update-option-a-keep-the-history-period) | Monthly update, option A: keep the history period |
| [11](#11-monthly-update-option-b-saved-historyjson) | Monthly update, option B: saved `history.json` |
| [12](#12-look-at-the-results) | Look at the results |
| [13](#13-save-the-results) | Save the results |
| [14](#14-speed-and-printing-settings) | Speed and printing settings |

**More tools**
- [A. Check your archive and keywords before a long run](#a-check-your-archive-and-keywords-before-a-long-run)
- [B. Summaries and transformations](#b-summaries-and-transformations)
- [C. More charts](#c-more-charts)
- [D. Reports and other file formats](#d-reports-and-other-file-formats)
- [E. Other ways to run: the `run_index` family](#e-other-ways-to-run-the-run_index-family)
- [F. Building blocks for full control](#f-building-blocks-for-full-control)

**Reference**
- [All settings of `build_index`](#all-settings-of-build_index)
- [Outputs](#outputs)
- [With history or without](#with-history-or-without)
- [Method](#method)
- [Speed](#speed)
- [Troubleshooting](#troubleshooting)
- [Development and tests](#development-and-tests)
- [Citation](#citation)
- [License](#license)

---

## Install

CAPEnewsindex needs Python 3.10 or newer.

```bash
pip install "CAPEnewsindex[plot,excel]"
```

| Extra | Adds | Needed for |
| --- | --- | --- |
| `plot` | matplotlib | `result.plot()`, the PNG chart and the chart functions (the dashboard needs nothing extra) |
| `excel` | openpyxl | the Excel workbook |
| `plotly`, `seaborn` | plotly, seaborn | other chart styles (`backend="plotly"` / `"seaborn"`) |
| `parquet` | pyarrow | `.parquet` files |
| `gsheet` | gspread | saving to Google Sheets |
| `docx`, `pdf` | python-docx, fpdf2 | Word / PDF reports |
| `test` | pytest | running the tests |

Check the install:

```bash
python -c "import CAPEnewsindex as ni; print(ni.__version__)"
```

To upgrade, run `pip install -U "CAPEnewsindex[plot,excel]"`. To install the latest code from GitHub, run `pip install "CAPEnewsindex[plot,excel] @ git+https://github.com/CAPE-ERC/cape-newsindex.git"`.

---

## Quick start

```python
import CAPEnewsindex as ni

result = ni.build_index(
    archive   = "Scrapped_Top_Articles",     # one sub-folder per country
    keywords  = "my_keywords.xlsx",          # your keywords (see "What you need")
    countries = ["Nigeria", "Ghana"],
    start     = "2015-01",
    history   = ("2015-01", "2025-12"),
    output    = "my_results",                # writes epu_dashboard.html and epu_results.xlsx
)
result.show()
```

Open `my_results/epu_dashboard.html` in any browser. The same code works in a script, in Jupyter and in VS Code.

> **Paths on Windows.** Write full paths as raw strings, `r"G:\My Drive\...\Scrapped_Top_Articles"`, or build them with `os.path.join(folder, "Scrapped_Top_Articles")`. A plain string with a variable's name inside it, such as `"articles\Scrapped_Top_Articles"`, does **not** use the variable `articles`.

---

## What you need

### The article archive

One folder per country, then one per newspaper, then one per month:

```
Scrapped_Top_Articles/
├── Nigeria/
│   ├── Punch/
│   │   ├── 2024-01/
│   │   │   └── articles_1.csv.gz
│   │   └── 2024-02/ ...
│   └── Vanguard/ ...
└── Ghana/ ...
```

Each file is a `.csv` or `.csv.gz` with the columns `site, date, title, url, text`, one row per article. The country folder names are the names you use everywhere else: in `countries=`, in the keyword file and in the GDP file.

### Your keywords

You always supply the keywords, so the index is never a black box. Every run prints the terms it used, and they also appear in the dashboard, in the Excel file and in `result.keywords`. See [use case 9](#9-keywords-start-from-the-template-or-write-your-own) for the formats.

### A GDP file (only for group indices)

GDP is never bundled; you supply it. Use a CSV or Excel file with a country column, a year column and one numeric GDP column:

```
Country,Year,GDP
Nigeria,2023,1360.2
Nigeria,2024,1420.8
Ghana,2023,230.1
...
```

- Annual values are interpolated to monthly values (log-linear) and held flat after the last year.
- Common spellings are matched automatically: `Burkina Faso` → `Burkina-Faso`, `Cabo Verde`/`Côte d'Ivoire` → `Cape Verde`/`Ivory Coast`, `Democratic Republic of the Congo` → `Congo DRC`, `The Gambia` → `Gambia`.
- Countries without GDP still get their own index. They are listed in a note and left out of the group indices.

---

# Use cases with `build_index`

`build_index` is the one call most users need. It checks everything first, reads the archive once, and gives you both the with-history and no-history versions. Any setting you leave empty is skipped (`None`, `""`, `[]` and `{}` all count as empty).

### 1. One country

```python
result = ni.build_index("Scrapped_Top_Articles", "my_keywords.xlsx", "Nigeria", "2024-01", "2026-10")
```

> **Note:** a single country can be given as plain text. Names are checked against the archive's folders, and a typo gets a suggestion ("Did you mean 'Nigeria'?").

### 2. Several countries, or all of them

```python
result = ni.build_index("Scrapped_Top_Articles", "my_keywords.xlsx", ["Nigeria", "Ghana", "Kenya"], "2024-01")
result = ni.build_index("Scrapped_Top_Articles", "my_keywords.xlsx", "all", "2024-01")   # every country folder
```

> **Note:** with `end` left out, the run goes up to the latest month in the archive. Every country must have terms for every keyword group of the index; if one doesn't, the run stops before reading anything and says which one.

### 3. No history: quick exploration

```python
result = ni.build_index("Scrapped_Top_Articles", "my_keywords.xlsx", ["Nigeria", "Ghana"], "2024-01", "2026-10")
```

> **Note:** without `history`, the index is scaled on `start`..`end` itself, so 100 = the average of that window. If you change the window, all values change. Use this to explore. It needs at least two months.

### 4. With history: the version to publish

```python
result = ni.build_index(
    "Scrapped_Top_Articles", "my_keywords.xlsx", ["Nigeria", "Ghana"], "2015-01", "2026-10",
    history = ("2015-01", "2025-12"),
)
```

> **Note:** the scaling is fixed on the history period (100 = the 2015–2025 average). Any window then gives **exactly the same values** for the months it covers, and past values never change when months are added. You get both versions; choose with `version="history"`, `"no history"` or `"both"` in `show`, `plot` and `save`.

### 5. Other indices: TPU, ETU, PU, EgPU, EPUV, ...

Change `index` (two or more keyword groups) and, if you like, `name`:

```python
result = ni.build_index(archive, keywords, ["Nigeria", "Ghana"], "2015-01",
                        index=["trade", "policy", "uncertainty"])                  # TPU

index = ["economic", "policy", "uncertainty"]                 # EPU (the default)
index = ["trade", "policy", "uncertainty"]                    # TPU
index = ["economic", "trade", "uncertainty"]                  # ETU
index = ["energy", "policy", "uncertainty"]; name = "EgPU"    # EgPU (initials alone would give "EPU")
index = ["policy", "uncertainty"]                             # PU
index = ["economic", "policy", "value_chain"]                 # EPV
index = ["economic", "policy", "uncertainty", "value_chain"]  # EPUV
```

> **Note:**
> - An article counts when it contains at least one term from **every** group. The method is the same for all indices.
> - Group names ignore case (`"Trade"` = `"trade"`).
> - The groups must be in your keyword file for every country you run. Any group name works: `energy`, `value_chain`, `climate`, ...
> - The library has no built-in index names: `name` is your acronym (default: the initials of the groups). It names the value column, the files and the dashboard: `result.country["TPU"]`, `tpu_dashboard.html`, `tpu_results.xlsx`.

### 6. Group index: all countries together

```python
result = ni.build_index(
    archive, keywords, ["Nigeria", "Ghana", "Kenya"], "2015-01", "2026-10",
    history = ("2015-01", "2025-12"),
    gdp     = "my_gdp.csv",
)
result.groups              # one GDP-weighted series: "All countries"
```

> **Note:** with `gdp` and no `groups`, all countries in the run form one block. Each country's index becomes a z-score over the scaling period, and the block is their GDP-weighted average, shown as 100 + 10 × the standardised value. `result.groups` is the with-history version; `result.groups_no_history` is the no-history version.

### 7. African regions and Africa as a whole

```python
result = ni.build_index(
    archive, keywords, "all", "2015-01", "2026-10",
    history = ("2015-01", "2025-12"),
    gdp     = "my_gdp.csv",
    groups  = "africa",                  # Central, East, North, Southern, West + Africa
    output  = "EPU_Africa_2026_10",
)
result.groups                            # the five regions and Africa, with history
result.groups_no_history
```

> **Note:** `groups="africa"` is a built-in shortcut. The library knows which countries belong to each region (`ni.AFRICA_REGIONS`), and **Africa** is all 54 together. GDP is not built in, so `gdp` is still required. A country without GDP is left out of the regions with a note, but keeps its own index. The membership is:

| Region | Countries |
| --- | --- |
| Central (7) | Cameroon, Central African Republic, Chad, Congo, Congo DRC, Equatorial Guinea, Gabon |
| East (13) | Burundi, Comoros, Djibouti, Eritrea, Ethiopia, Kenya, Rwanda, Seychelles, Somalia, South Sudan, Sudan, Tanzania, Uganda |
| North (6) | Algeria, Egypt, Libya, Mauritania, Morocco, Tunisia |
| Southern (13) | Angola, Botswana, Eswatini, Lesotho, Madagascar, Malawi, Mauritius, Mozambique, Namibia, Sao Tome and Principe, South Africa, Zambia, Zimbabwe |
| West (15) | Benin, Burkina-Faso, Cape Verde, Gambia, Ghana, Guinea, Guinea-Bissau, Ivory Coast, Liberia, Mali, Niger, Nigeria, Senegal, Sierra Leone, Togo |

```python
for region, members in ni.AFRICA_REGIONS.items():   # see it in Python
    print(region, members)
```

### 8. Your own blocks of countries, any continent

```python
result = ni.build_index(
    archive, keywords, ["Nigeria", "Ghana", "Kenya", "Egypt"], "2015-01", "2026-10",
    history = ("2015-01", "2025-12"),
    gdp     = "my_gdp.csv",
    groups  = {
        "West":     ["Nigeria", "Ghana"],
        "East":     ["Kenya"],
        "All four": ["Nigeria", "Ghana", "Kenya", "Egypt"],
    },
)

groups = {"Euro area": ["Germany", "France", "Italy", "Spain"], "Nordics": ["Sweden", "Norway", "Denmark"]}
```

> **Note:**
> - A dict replaces the African preset. Use it to reclassify a country, or for any continent; Europe works the same way as long as the archive and the GDP file have those countries.
> - A country can be in several blocks.
> - Countries in `groups` that are not in the run are listed and left out.
> - `ni.countries()` gives the ISO 3166-1 table with UN continent and region columns, which helps build blocks: `ni.countries().query("continent == 'Europe'")`.

### 9. Keywords: start from the template, or write your own

**Start from the bundled dictionary.** It covers 54 African countries with economic, policy, uncertainty and trade terms. Write it in the format you like, then edit it:

```python
ni.keywords_template("my_keywords.xlsx")                                    # all countries, Excel
ni.keywords_template("my_keywords.txt", countries=["Nigeria", "Ghana"])     # some countries, text
ni.keywords_template("my_keywords.csv", groups=["trade", "policy", "uncertainty"])
ni.keywords_template("my_keywords.json")
```

**Formats**, which all hold the same information:

| Format | Looks like |
| --- | --- |
| Excel `.xlsx` / CSV `.csv` | three columns, `country`, `group` and `term`, with one term per row (`Nigeria, economic, inflation`) |
| Text `.txt` | a `[Nigeria]` line, then a line per group (`economic:`, `policy:`, ...), each followed by its terms, one per line |
| JSON `.json` | `{"Nigeria": {"economic": [...], "policy": [...], "uncertainty": [...]}}` (the EPTU `ECONOMY_TERMS` schema also works) |
| Python dict | as below |

**A dict in your script:**

```python
keywords = {                                     # the same terms for every country
    "economic":    ["economy", "economic"],
    "policy":      ["policy", "central bank", "regulation", "tax"],
    "uncertainty": ["uncertain", "uncertainty"],
}
keywords = {                                     # terms per country
    "Nigeria": {"economic": ["economy", "naira"], "policy": ["CBN", "policy"], "uncertainty": ["uncertainty"]},
    "Ghana":   {"economic": ["economy", "cedi"],  "policy": ["BoG", "policy"], "uncertainty": ["uncertainty"]},
}
```

> **Note:**
> - Terms match as whole words or phrases, in any language and script, ignoring upper/lower case.
> - A country written as `*` (or a `[*]` section) adds its terms to every country.
> - You can add groups of your own (`energy`, `value_chain`, ...) and use them in `index`.
> - To check a file before a run: `ni.dictionary.validate(ni.dictionary.read("my_keywords.xlsx"))` lists empty groups and terms shared between groups.
> - To convert between formats: `ni.dictionary.save_keywords(ni.dictionary.read("my_keywords.xlsx"), "my_keywords.json")`.

### 10. Monthly update, option A: keep the history period

```python
result = ni.build_index(
    archive, keywords, ["Nigeria", "Ghana"], "2026-11", "2026-11",
    history = ("2015-01", "2025-12"),       # never change this between updates
    output  = "EPU_2026_11",                # a new folder each month
)
result.show(version="history")
```

> **Note:** because the history period stays the same, the new month is on exactly the same scale as everything you published before. The no-history block of a short run is scaled on just those months, so ignore it for updates. The history files come from the cache, but they are still checked, which can be slow on a cloud-synced drive (see option B).

### 11. Monthly update, option B: saved `history.json`

**Once**, save the history scaling:

```python
result = ni.build_index(
    archive, keywords, ["Nigeria", "Ghana"], "2015-01", "2026-10",
    history = ("2015-01", "2025-12"),
    output  = "EPU_history",
    files   = ["dashboard", "excel", "history"],      # "history" writes history.json
)
```

**Every month after**, run only the new month:

```python
result = ni.build_index(
    archive, keywords, ["Nigeria", "Ghana"], "2026-11", "2026-11",
    history = "EPU_history/history.json",
    output  = "EPU_2026_11",
)
result.show(version="history")
```

> **Note:**
> - `history.json` stores each newspaper's standard deviation (`sigma`) and each country's mean (`mu`). The update reuses them as they are, with no refitting, and gives exactly the same values as a full run. Only the new month's files are read, so it takes seconds.
> - Keep the same keywords and countries. If the keywords change, the run prints a note; make a new `history.json` then.
> - A newspaper that wasn't in the history period has no saved scaling, so it is left out.
> - With `gdp`, the history months are still read (from the cache) to standardise each country for the group index.

### 12. Look at the results

```python
result                              # a short overview
result.show()                       # last 6 months, both versions
result.show(months=12, version="history")
result.plot()                       # solid = with history, dashed = no history
result.plot(version="history", path="epu_chart.png")
result.table()                      # summary per country (latest, average, highest, ...)
```

| Attribute | What it holds |
| --- | --- |
| `result.country` | Index per country-month, with history when given. The value column is named after the index (`EPU`, `TPU`, ...), plus `M_t`, `mu` and `n_sites` (newspapers that month). |
| `result.no_history` | The no-history version of the same table. |
| `result.wide` / `result.wide_no_history` | One column per country, one row per month. |
| `result.groups` / `result.groups_no_history` | Group indices: `group`, `year_month`, `z`, `index`, `n_countries`, `weight_covered`. |
| `result.counts` | Articles per newspaper-month: `epu_articles` (matching) and `all_articles`. |
| `result.keywords` | The exact terms used, per country and group. |
| `result.history` | The fitted history scaling (or `None`). |
| `result.skipped_files` | Files that couldn't be read, with the reason. |
| `result.settings` | The settings of the run. |

> **Note:** all tables are pandas DataFrames, so you can continue with your own analysis, e.g. `result.wide.corr()`, `result.country.query("country == 'Nigeria'")`.

### 13. Save the results

```python
ni.build_index(..., output="my_results")                                   # save while building
result.save("my_results")                                                  # or later: dashboard + Excel
result.save("my_results", files="all")                                     # + CSV files + PNG chart
result.save("my_results", files=["dashboard", "excel", "history"])         # + history.json
result.save("my_results", files="excel", version="history")                # only the with-history tables
result.dashboard("my_results/epu_dashboard.html")                          # only the dashboard
```

> **Note:** a relative folder such as `"my_results"` is created next to your script (or notebook); a full path is used as given. Saving again to the same folder overwrites the files, so use a new folder per run you want to keep, e.g. `"EPU_2026_11"`.

### 14. Speed and printing settings

```python
result = ni.build_index(..., workers=4)        # use 4 processes (default: all CPU cores)
result = ni.build_index(..., cache=False)      # read every file again, ignoring the cache
result = ni.build_index(..., verbose=False)    # no printing
```

> **Note:** the cache (on by default) stores each file's result. A re-run reads only new or changed files, and changing the keywords re-reads that country automatically. Use `cache=False` only to rule the cache out when checking something. On a cloud-synced folder, making the archive available offline makes runs steadier.

---

# More tools

Everything below works on the tables in `result` (or any table with `country`, `year_month` and an `EPU` column).

> **Using these with an index not named EPU:** the summary, chart and report helpers in sections B–D read a column called `EPU`. For TPU, PU, etc., rename it first:
> `table = result.country.rename(columns={"TPU": "EPU"})`

### A. Check your archive and keywords before a long run

```python
ni.coverage("Scrapped_Top_Articles", countries=["Nigeria"])          # files and articles per country-month
ni.validate_archive("Scrapped_Top_Articles", countries=["Nigeria"])  # missing columns, empty files, wrong dates
kw = ni.dictionary.read("my_keywords.xlsx")
ni.dictionary_coverage(kw, "Scrapped_Top_Articles")                  # countries in the archive, the keywords, or both
ni.health_check("Scrapped_Top_Articles", "my_keywords.json")         # all of the above on a sample, in one call
```

> **Note:** use these when you add a new country or newspaper, or when a run's numbers look odd. For example, `coverage` shows a month with very few articles, and `validate_archive` finds files whose dates don't match their month folder. An empty `validate_archive` table means no problems.

### B. Summaries and transformations

```python
table = result.country
print(ni.summarize(table))                         # plain-English summary per country
ni.describe(table)                                 # min, max, mean, std and biggest monthly move per country
ni.top(table, n=5)                                 # the 5 highest country-months
ni.print_period(table, "2026-01", "2026-10")       # print a period
ni.resample(table, "Q")                            # quarterly averages ("A" = annual)
ni.rebase(table, ("2020-01", "2020-12"))           # rescale so 2020 = 100
ni.smooth(table, window=3)                         # adds an EPU_smoothed column (3-month average)
```

> **Note:** `rebase` only changes the reference level, not the index's shape. Use it to compare with a series based on another year. `resample` is for quarterly models or annual reports.

### C. More charts

```python
table = result.country
ni.theme("default")                                         # one style for all charts (call once at the top)
fig = ni.plot(table, kind="line")                           # one line per country ("bar", "area")
ni.plot_compare(table, countries=["Nigeria", "Ghana"])      # overlay of chosen countries
ni.plot_regions(result.groups)                              # one line per region/block
ni.plot_heatmap(table)                                      # country x month heatmap
ni.plot_rank(table, "2026-10")                              # countries ranked for one month
ni.plot_rolling(table, window=3)                            # raw and 3-month average
ni.plot_distribution(table, kind="box")                     # spread per country ("hist")
ni.plot_components(result.counts)                           # matching vs other articles over time
ni.plot_history(result.history)                             # each newspaper's history scaling
ni.plot_correlation(table.query("country == 'Nigeria'"), inflation_series)  # against another series
ni.plot_dashboard(table)                                    # trend, ranking and distribution in one figure
ni.save_plot(fig, "epu_chart.png")                          # save any chart
```

> **Note:** each function returns a figure you can show or save. Add `backend="plotly"` for interactive charts, or `backend="seaborn"` (needs the matching extra). `plot_correlation` takes one country and a pandas Series indexed by `"YYYY-MM"`, e.g. inflation or an exchange rate. The HTML dashboard already includes the main charts; these are for papers and slides.

### D. Reports and other file formats

```python
table = result.country
ni.report(table, "epu_report.html")            # one-page report (.html or .md)
ni.save_report(table, "epu_report.docx")       # also .pdf (needs the docx / pdf extra)

ni.save(table, "epu.csv")                      # format from the extension: .csv .xlsx .json .parquet
ni.save_excel(table, "epu.xlsx", sheet_by="country")       # one sheet per country
ni.save_all({"country": result.country, "groups": result.groups}, "out", formats=("csv", "xlsx"))
ni.save_versioned(table, "archive_of_runs", base_name="epu")   # epu_20261110T211547.csv: never overwrites
ni.load("epu.csv")                             # read a saved table back

import sqlite3
ni.save_sql(table, sqlite3.connect("epu.db"), "epu")       # into a database table
ni.save_gsheet(table, "https://docs.google.com/spreadsheets/d/...")   # into a Google Sheet (gsheet extra)
ni.autosave(table, {"folder": "out", "format": "csv", "name": "epu"})
```

> **Note:** `result.save(...)` already writes the dashboard and the Excel workbook. Use these for other destinations:
> - `save_versioned` keeps every monthly run side by side;
> - `save_sql` and `save_gsheet` feed a database or a shared sheet. `save_gsheet` uses your own Google credentials (a `gspread` service account).

### E. Other ways to run: the `run_index` family

These return the index as a plain DataFrame, for the EPU groups (economic, policy, uncertainty). They take a **keyword file path**, or `None` for the bundled dictionary.

```python
kw = "my_keywords.json"
ni.run_index(archive, kw, "2024-01", "2026-10", countries=["Nigeria"])          # no history
table, history = ni.run_index_with_history(archive, kw, windows=[("2026-01", "2026-10")],
                                           history_start="2015-01", history_end="2025-12")
ni.quick_index(archive, kw, "Nigeria", 2025)                                   # one country, one year
ni.index_all(archive, kw, "2024-01", "2026-10")                                # every country folder
ni.index_countries(archive, kw, ["Nigeria", "Ghana"], "2024-01", "2026-10")
ni.index_region(archive, kw, "West", "2024-01", "2026-10")                     # all countries of a region
ni.index_since(archive, kw, months_back=12)                                    # the last 12 months
ni.rerun(previous_table)                                                       # repeat the exact same call
```

> **Note:** use `build_index` unless you need one of these shortcuts. `index_region` skips region members that have no folder. `index_since` counts back from today's date. `rerun` repeats a call from the settings stored on its result table, which makes a quick monthly refresh. Pass `history=` to `run_index_with_history` to reuse a saved `History`.

### F. Building blocks for full control

`build_index` is assembled from these functions. Use them to change a single step, e.g. counting once and trying several history periods.

```python
kw     = ni.dictionary.read("my_keywords.xlsx")                       # any format, or a dict
counts = ni.index.count_archive(archive, kw, countries=["Nigeria", "Ghana"],
                                groups=("economic", "policy", "uncertainty"))   # per newspaper-month
no_hist = ni.index.compute_index(counts, "2015-01", "2026-10")        # no-history index
history = ni.index.fit_history(counts, "2015-01", "2025-12")          # fit sigma and mu
scored  = ni.index.score(counts, history)                             # with-history index
later   = ni.index.score_windows(counts, history, [("2026-01", "2026-10")])
history.save("history.json"); history = ni.index.History.load("history.json")
```

**Group indices with other weights:**

```python
gdp_w   = ni.weights.gdp("my_gdp.csv", value_col="GDP", end="2026-10")           # columns: country, year_month, gdp
blocks  = ni.aggregate.aggregate(scored, gdp_w, history=history)                  # 5 African regions + Africa
blocks  = ni.aggregate.aggregate(scored, gdp_w, groups={"West": ["Nigeria", "Ghana"]},
                                 history=history, include_africa=False)
equal   = ni.aggregate.aggregate(scored, ni.weights.equal, history=history)       # every country counts the same
pop_w   = ni.weights.population("my_population.csv", end="2026-10")              # column: population
by_pop  = ni.aggregate.aggregate(scored, pop_w, weight_col="population", history=history)
mix     = ni.weights.pca(gdp_w.merge(pop_w, on=["country", "year_month"]))        # column: pca_weight
by_pca  = ni.aggregate.aggregate(scored, mix, weight_col="pca_weight", history=history)
```

**Text, matching and deduplication:**

```python
articles = ni.read_articles(archive, countries=["Ghana"])            # every article as a DataFrame
ni.match.find_terms("Fiscal policy uncertainty hits the economy", ["policy", "uncertainty", "GDP"])
ni.match.is_epu(title, text, economic_terms, policy_terms, uncertainty_terms)     # one article
ni.dedup.canonical_url("HTTPS://www.Punchng.com/news/a?utm_source=x#top")          # -> https://www.punchng.com/news/a
ni.dedup.dedupe(articles)                                              # drop duplicates per country-month
ni.index.count(articles, kw)                                           # counts from articles in memory
```

> **Note:** `read_articles` loads everything into memory, so use it on a few countries to inspect articles: see why one matched, or look for words to add. `count_archive` is the fast parallel path behind `build_index`.

| Module | What it does |
| --- | --- |
| `simple` | `build_index` and its result (`show`, `plot`, `save`, `dashboard`) |
| `fastscan` | the parallel archive reader and cache |
| `match` | text normalization and whole-word/phrase matching in any script |
| `dictionary` | keyword files in all formats: `read`, `template`, `save_keywords`, `to_table`, `validate`, `fingerprint` |
| `dedup` | duplicate removal by canonical URL, or title and text |
| `index` | counts per newspaper-month; scaling with or without a history; `History` |
| `pipeline` | the `run_index` family |
| `aggregate`, `weights` | country z-scores and weighted group series (GDP, population, equal, PCA, your own) |
| `diagnostics` | `coverage`, `validate_archive`, `dictionary_coverage`, `health_check` |
| `report`, `plot`, `save` | summaries, charts and file export for any result table |
| `countries` | `ni.countries()`: ISO 3166-1 table with UN M49 continent and region |

---

# Reference

## All settings of `build_index`

```python
ni.build_index(archive, keywords, countries="all", start="2015-01", end=None, *,
               history=None, index=("economic", "policy", "uncertainty"), name=None,
               gdp=None, groups=None, output=None, files=("dashboard", "excel"),
               workers=None, cache=True, verbose=True)
```

| Setting | What it is | When empty |
| --- | --- | --- |
| `archive` | Folder holding one sub-folder per country. | required |
| `keywords` | Your keywords: `.xlsx`, `.csv`, `.txt`, `.json` file, or a dict. | required |
| `countries` | `"Nigeria"`, `["Nigeria", "Ghana"]` or `"all"`. | all countries |
| `start`, `end` | First and last month, `"YYYY-MM"`. | `start` 2015-01; `end` = latest month |
| `history` | `("2015-01", "2025-12")`, or a saved `history.json`. | no-history only |
| `index` | Two or more keyword groups an article must all contain. | economic, policy, uncertainty |
| `name` | Your acronym for the index. | initials of the groups |
| `gdp` | Your GDP file (CSV/Excel) or DataFrame. | no group index |
| `groups` | `"africa"`, or `{"Block": [countries], ...}`. Needs `gdp`. | one block of all countries (if `gdp`) |
| `output` | Folder to save to. | nothing saved |
| `files` | Any of `"dashboard"`, `"excel"`, `"csv"`, `"chart"`, `"history"`, or `"all"`. | dashboard + Excel |
| `workers` | Number of parallel processes. | all CPU cores |
| `cache` | Reuse per-file results from earlier runs. | `True` |
| `verbose` | Print progress and a summary. | `True` |

## Outputs

Saving writes two files by default, named after your index (`epu_...`, `tpu_...`):

- **`epu_dashboard.html`**: one self-contained file with separate pages:

  | Page | What it shows |
  | --- | --- |
  | **Overview** | latest value and monthly change for every group and country (countries organised by region), rankings for the latest month, a summary table |
  | **Regions** | one chart per region or block of countries (with its member list), and their last 12 months |
  | **Countries** | one chart per country, organised by region, with a search box and region shortcuts; last 12 months and all months |
  | **Newspapers** | articles per country and per newspaper, and articles per month for each country |
  | **Keywords** | the number of terms per group and every term used, per country |
  | **About** | how to read the index, the method, the run settings, and any files that could not be read |

  A switch at the top changes every page between **With history** and **No history**. Hover over a chart to see each month's value. It opens in any browser, works offline, needs no extra packages and can be emailed as is.
- **`epu_results.xlsx`**: every table, one sheet each.

| `files=` option | Adds |
| --- | --- |
| `"csv"` | the same tables as CSV files |
| `"chart"` | the main chart as a PNG |
| `"history"` | `history.json`, the fixed scaling for monthly updates |
| `"all"` | dashboard, Excel, CSV and chart |

## With history or without

When you give a history period, both versions come from the same single read.

| | With history | No history |
| --- | --- | --- |
| 100 equals | the history-period average | the `start`..`end` average |
| Past values when months are added | never change | shift |
| Same month, different run window | identical | different |
| Use it for | publishing, monthly updates, group indices | exploring; when there is no long history yet |

## Method

1. **Classify.** An article counts if its title or text contains at least one term from every keyword group of the index, for its country. Terms match as whole words or phrases, in any script. Duplicates within a country-month are removed by canonical URL, or by title and text when there is no URL.
2. **Share.** `S_it` = matching articles / all articles, for newspaper *i* in month *t*.
3. **Standardise.** `N_it = S_it / σ_i`, where `σ_i` is the newspaper's standard deviation over the scaling period: the history period, or `start`..`end` with no history. A newspaper needs at least two months in that period.
4. **Average and rescale.** `M_t` = mean of `N_it` across newspapers; `index_t = 100 · M_t / μ`, with `μ` the mean of `M_t` over the scaling period.
5. **Group index.**
   - Each country's index becomes a z-score over the scaling period.
   - A block's value is the weighted average of its countries' z-scores (GDP by default).
   - The result is rescaled to 100 + 10 × the standardised value.

Reference: Baker, S. R., Bloom, N. and Davis, S. J. (2016), "Measuring Economic Policy Uncertainty", *Quarterly Journal of Economics* 131(4), 1593–1636.

## Speed

- **Parallel reading.** Files are read in parallel on all CPU cores, largest first, with a fast CSV reader instead of pandas.
- **Small memory.** Only one match flag and one 64-bit deduplication hash are kept per article, so memory stays small at any archive size.
- **Caching.** Per-file results are cached; a re-run reads only new or changed files.
- **One read, both versions.** The with-history and no-history versions come from the same read.

Typical timings:

| Run | Time |
| --- | --- |
| One country, 28,800 articles (2 cores) | 1.5 s (previous engine: 10.8 s) |
| Two countries, 3.7 million articles, from the cache | about 5–7 s |

The first run on a cloud-synced folder (e.g. Google Drive) is slower while files download. Making the archive available offline helps. `tests/test_fastscan.py` checks that the fast engine gives exactly the same results as a plain pandas implementation on randomized messy archives.

## Troubleshooting

| Message or symptom | What to do |
| --- | --- |
| `archive is a tuple, not a path` | Remove the trailing comma after `archive = "..."` (or `keywords = "..."`). |
| `'Nigera': no folder with this name in the archive. Did you mean 'Nigeria'?` | Fix the spelling; names must match the archive's country folders. |
| `'Ghana': no energy keywords (an article must match every group ...)` | Add that group to your keyword file for every country in the run. |
| `Note: groups need a GDP file (gdp=...), so the group index is skipped.` | Add `gdp="my_gdp.csv"`. |
| `Note: no GDP for ... -- left out of the group index.` | Add those countries to your GDP file, or accept that they're left out. |
| `The GDP file needs a country column, a year column and one numeric GDP column` | Check the GDP file's headers. |
| `Note: this history was fitted with different keywords ...` | Your keywords changed since `history.json` was made; make a new one. |
| `FileNotFoundError` on a path with `\` | Use `r"..."` or `os.path.join(...)`; see [Quick start](#quick-start). |
| All values near 100 in a short run | That's the no-history version of a short window; use `history=` and `version="history"`. |
| `KeyError: 'EPU'` in a chart or summary helper | Rename your index's column to `EPU` first (see [More tools](#more-tools)). |
| Files saved in an unexpected folder | Relative `output` folders are created next to your script; use a full path to choose. |
| `Install matplotlib to see charts` | `pip install "CAPEnewsindex[plot,excel]"`. |
| Some files listed as skipped | They couldn't be read (empty, corrupt, wrong columns). See `result.skipped_files`; the rest of the run is unaffected. |
| A run is much slower than usual | Usually the cloud drive syncing; make the archive available offline, or use [option B](#11-monthly-update-option-b-saved-historyjson). |
| `No module named CAPEnewsindex` | Install it into the Python you run: `python -m pip install CAPEnewsindex`. |

## Development and tests

```bash
git clone https://github.com/CAPE-ERC/cape-newsindex.git
cd cape-newsindex
python -m pip install -e ".[test,plot,excel]"
python -m pytest
```

The [`examples/`](examples/) folder has:
- `run_epu.py`, a ready-to-edit script with every setting at the top;
- `test_with_drive.ipynb`, a notebook for a real archive;
- `sample_articles.xlsx`, 24 hand-labelled articles, with `test_with_excel.ipynb`, which checks every number against hand-computed values.

## Citation

If you use CAPEnewsindex in your work, please cite the package and the method:

```
CAPE Economic Research and Consulting (2026). CAPEnewsindex: news-based uncertainty
indices from newspaper archives (version 1.0.0). https://github.com/CAPE-ERC/cape-newsindex

Baker, S. R., Bloom, N. and Davis, S. J. (2016). Measuring Economic Policy Uncertainty.
Quarterly Journal of Economics, 131(4), 1593–1636.
```

## License

MIT. See [LICENSE](LICENSE).

© CAPE Economic Research and Consulting.
