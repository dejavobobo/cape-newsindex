# CAPEnewsindex

Build news-based uncertainty indices from newspaper archives -- Economic Policy Uncertainty (EPU), or any index you define from two or more keyword groups, under your own name -- with the Baker, Bloom and Davis (2016) method, for any country and any language.

You bring the scraped articles and your keywords; `CAPEnewsindex` gives you a monthly index per country, with or without a history period, GDP-weighted indices for any blocks of countries, and a dashboard to read and share them.

## Usage

### 1. Install

```bash
pip install CAPEnewsindex[plot,excel]
```

To use a local copy of this repository instead, run this **inside the repository folder** (changes take effect without reinstalling):

```bash
cd path/to/cape-newsindex
python -m pip install -e ".[plot,excel]"
python -c "import CAPEnewsindex as ni; print(ni.__version__)"
```

Requires Python 3.10+. `plot` adds matplotlib (charts), `excel` adds openpyxl (Excel output).

### 2. Build an index (one call)

```python
import CAPEnewsindex as ni

result = ni.build_index(
    archive   = "Scrapped_Top_Articles",                    # folder with one sub-folder per country
    keywords  = "my_keywords.json",                         # or .xlsx / .csv / .txt
    countries = ["Nigeria", "Ghana"],                       # one name, a list, or "all"
    start     = "2024-01",
    end       = "2026-09",                                  # None = latest month in the archive

    index     = ["economic", "policy", "uncertainty"],      # keyword groups an article must all contain
    name      = "EPU",                                      # your acronym; None = initials of the groups
    history   = ("2015-01", "2023-12"),                     # None = no history only
    gdp       = None,                                       # your GDP file -> group index
    groups    = None,                                       # e.g. {"West Africa": ["Nigeria", "Ghana"]} (needs gdp)
    output    = "my_results",                               # None = don't save
)
result.show()
```

Anything left empty is skipped:

| Setting | When empty |
| --- | --- |
| `index` | `["economic", "policy", "uncertainty"]`. |
| `name` | The initials of the groups (`"EPU"`). |
| `history` | Only the no-history index is made. |
| `gdp` | No group index. If you gave `groups` without `gdp`, a one-line note says it was skipped; it doesn't fail. |
| `groups` (with `gdp`) | One GDP-weighted index for all the countries together. |
| `output` | Nothing is saved; you can still call `result.save(...)` later. |
| `end` | The latest month in the archive. |
| `countries` | All countries. |

`None`, `""`, `[]` and `{}` all count as empty.

### 3. Other indices

Change only `index` (the keyword groups, two or more) and, if you like, `name`:

```python
index = ["economic", "policy", "uncertainty"]                 # EPU (the default)
index = ["trade", "policy", "uncertainty"]                    # TPU
index = ["economic", "trade", "uncertainty"]                  # ETU
index = ["energy", "policy", "uncertainty"]; name = "EgPU"    # EgPU (initials alone would give "EPU")
index = ["policy", "uncertainty"]                             # PU
index = ["economic", "policy", "value_chain"]                 # EPV
index = ["economic", "policy", "uncertainty", "value_chain"]  # EPUV
```

The groups must be in your keyword file for every country you run (any group name works: `energy`, `value_chain`, `climate`, ...). An article counts when it contains at least one term from **every** group; the scaling method is the same for all. The name is used for the value column, the files and the dashboard: `result.country["EgPU"]`, `egpu_dashboard.html`, `egpu_results.xlsx`.

### 4. Group index for any blocks of countries (needs your GDP file)

```python
result = ni.build_index(
    archive, keywords, ["Nigeria", "Ghana", "Kenya", "Egypt"], "2024-01", "2026-09",
    history = ("2015-01", "2023-12"),
    gdp     = "my_gdp.csv",                                 # country, year and GDP columns (CSV or Excel)
    groups  = {"West": ["Nigeria", "Ghana"], "East": ["Kenya"], "All": ["Nigeria", "Ghana", "Kenya", "Egypt"]},
    output  = "my_results",
)
result.groups              # with history
result.groups_no_history   # no history
```

A country can be in several blocks; any continent works (e.g. `{"Euro area": ["Germany", "France", "Italy"]}`). `groups="africa"` gives the five African regions plus Africa; without `groups`, one block of all countries in the run. Country names in the GDP file must match the archive's folder names; countries without GDP data are named and left out.

### 5. Your keywords

```python
ni.keywords_template("my_keywords.xlsx")                                 # start from the production dictionary
ni.keywords_template("my_keywords.txt", countries=["Nigeria", "Ghana"])  # or .csv / .json
```

Edit the file -- add or remove terms, or add groups of your own such as `energy` or `value_chain` -- then pass it as `keywords="my_keywords.xlsx"`.

### 6. Look at and save the results

```python
result.show()                                              # both versions (with and without history)
result.show(version="no history")                          # just one
result.plot()                                              # solid = with history, dashed = no history
result.save("my_results")                                  # dashboard + Excel
result.save("my_results", files="all")                     # + CSV files + chart
result.save("my_results", files=["dashboard", "history"])  # + history.json, to reuse next month

result.country        # index per country-month (the column is named after the index: EPU, TPU, ...)
result.no_history     # the no-history version
result.wide           # one column per country
result.counts         # articles per newspaper-month
result.keywords       # the exact terms used
result.skipped_files  # files that couldn't be read
```

### 7. Next month, same scaling

Save the history scaling once (`files=["dashboard", "excel", "history"]`), then reuse it:

```python
result = ni.build_index(
    archive, keywords, ["Nigeria", "Ghana"], "2026-10", "2026-10",
    history = "my_results/history.json",
    output  = "my_results_2026_10",
)
```

A ready-to-edit script is in [`examples/run_epu.py`](examples/run_epu.py).

## Good to know

- `build_index` checks everything first -- folders, country names, month format, that every country has terms in every keyword group of the index -- suggests a fix when something is misspelled ("Did you mean 'Nigeria'?"), and skips (and lists) article files it can't read instead of stopping.
- Relative paths such as `"my_results"` are taken next to your script (in Jupyter: next to the notebook).
- The archive layout is the scraper's: `<archive>/<country>/<newspaper>/<YYYY-MM>/articles_*.csv(.gz)`, each file with `site, date, title, url, text` columns.

## Keyword files

You always supply the keywords, so nothing is hidden. All four formats hold the same information:

| Format | Looks like |
| --- | --- |
| Excel `.xlsx` / CSV `.csv` | three columns -- `country`, `group`, `term` -- one term per row (`Nigeria, economic, inflation`) |
| Text `.txt` | a `[Nigeria]` line, then a line per group (`economic:`, `policy:`, ...), each followed by its terms, one per line |
| JSON `.json` | `{"Nigeria": {"economic": [...], "policy": [...], "uncertainty": [...]}}` (the EPTU schema also works) |
| Python dict | the same as JSON; or one `{"economic": [...], ...}` for every country |

A group can have any name (`economic`, `trade`, `energy`, `value_chain`, ...). A country written as `*` (or a `[*]` section) adds its terms to every country. The bundled production dictionary (54 African countries; economic, policy, uncertainty and trade terms) is only a starting point for `ni.keywords_template(...)`. Every run lists the terms used per country; they are also in `result.keywords`, the dashboard and the Excel file.

## With history or without

When you give a history period you get both versions from the same single read; pick one with `version="history"`, `"no history"` or `"both"` (default) in `show`, `plot` and `save`.

- **With history** -- each newspaper's scaling and the country mean are fixed on the history period, so 100 = the history average and past values never change when months are added. Use it for anything you publish or update monthly.
- **No history** -- scaled on `start`..`end` itself (100 = that window's average); values shift when the window changes. Use it to explore, or when there is no long history yet.

## Outputs

Saving writes two files, named after the index (e.g. `epu_...`, `tpu_...`):

- **`epu_dashboard.html`** -- one page with every chart and table: latest values, each country, group index, newspapers and articles, the keywords used, and how to read it. Opens in any browser, works offline, can be emailed as is.
- **`epu_results.xlsx`** -- every table, one sheet each.

`files=` adds `"csv"`, `"chart"` (PNG) or `"history"` (`history.json`), or `"all"`.

## Method

- **Classify.** An article counts if its title or text contains at least one term from every keyword group of the index, for its country -- whole words or phrases, any script. Duplicates within a country-month are removed by URL, or by title and text when there is no URL.
- **Share.** `S_it` = matching articles / all articles, for newspaper *i* in month *t*.
- **Standardise.** `N_it = S_it / sigma_i`, with `sigma_i` the newspaper's standard deviation over the scaling period (the history period, or `start`..`end` with no history). A newspaper needs at least two months there.
- **Average and rescale.** `M_t` = mean of `N_it` across newspapers; `index_t = 100 * M_t / mu`, with `mu` the mean of `M_t` over the scaling period.
- **Group index.** Each country's index becomes a z-score over the scaling period; a block's value is the GDP-weighted average of its countries' z-scores, rescaled to 100 + 10 x standardised value.

Following Baker, Bloom and Davis (2016), "Measuring Economic Policy Uncertainty", *Quarterly Journal of Economics* 131(4).

## Speed

Files are read in parallel on all CPU cores, without pandas, keeping only one match flag and one 64-bit deduplication hash per article, so memory stays small at any archive size. Per-file results are cached, so a re-run only reads new or changed files. On a 28,800-article test archive, one country took 1.5 s (2 cores; 10.8 s with the previous engine), and a re-run from the cache well under a second. The first run on a cloud-synced folder (e.g. Google Drive) is slower while files download. `tests/test_fastscan.py` checks that the results equal a plain pandas implementation on randomized messy archives.

## Advanced use

`build_index` is built from smaller functions that return plain DataFrames:

```python
kw = ni.dictionary.read("my_keywords.xlsx")
counts = ni.index.count_archive(archive, kw, groups=("economic", "policy", "uncertainty"))  # per newspaper-month
history = ni.index.fit_history(counts, "2015-01", "2023-12")
scored = ni.index.score(counts, history)
blocks = ni.aggregate.aggregate(scored, ni.aggregate.monthly_gdp("my_gdp.csv"), groups={"West": ["Nigeria", "Ghana"]})
```

| Module | What it does |
| --- | --- |
| `simple` | `build_index` and its result (`show`, `plot`, `save`, `dashboard`) |
| `fastscan` | the parallel archive reader |
| `match` | text normalization and whole-word/phrase matching in any script |
| `dictionary` | keyword files in all formats: `read`, `load`, `template`, `validate`, `fingerprint` |
| `dedup` | duplicate removal by canonical URL, or title and text |
| `index` | counts per newspaper-month; scaling with or without a history |
| `pipeline` | `run_index`, `run_index_with_history`: DataFrame versions of `build_index` |
| `aggregate`, `weights` | country z-scores and weighted group series (GDP, population, equal, PCA, your own) |
| `diagnostics` | archive checks before a long run: `coverage`, `validate_archive`, `health_check` |
| `report`, `plot`, `save` | summaries, charts and file export for any result table |
| `countries` | `ni.countries()`: ISO 3166-1 table with UN M49 continent and region, for building groups |

## Examples and tests

[`examples/`](examples/) has a ready-to-edit script (`run_epu.py`), a notebook for a real archive (`test_with_drive.ipynb`), and 24 hand-labeled articles (`sample_articles.xlsx`) with a notebook that checks every number against hand-computed values (`test_with_excel.ipynb`). To run the tests:

```bash
python -m pip install -e ".[test,plot,excel]"
python -m pytest
```

## License

MIT. See [LICENSE](LICENSE).
