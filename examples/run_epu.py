"""Build the EPU index -- edit the settings, then run:  python run_epu.py"""

import CAPEnewsindex as ni

# ---- Settings ----------------------------------------------------------------
ARCHIVE = r"G:\path\to\Scrapped_Top_Articles"   # folder with one sub-folder per country
KEYWORDS = "my_keywords.xlsx"                       # or .csv / .txt / .json
COUNTRIES = ["Nigeria", "Ghana"]                    # one name, a list, or "all"
START, END = "2024-01", "2026-09"   # None = first / latest month in the archive
INDEX = ["economic", "policy", "uncertainty"]   # EPU; e.g. ["policy", "uncertainty"] for PU
NAME = None            # your acronym, e.g. "EPU"; None = initials of the groups

HISTORY = None         # e.g. ("2015-01", "2024-12"); None = no history
GDP_FILE = None        # your GDP file, e.g. r"C:\data\gdp_ppp.csv" -> adds group indices (GDP-weighted)
GDP_NAMES = None       # renames for GDP-file countries spelled differently, e.g. {"Burkina Faso": "Burkina-Faso"}
GROUPS = None          # your blocks, e.g. {"West Africa": ["Nigeria", "Ghana"]}; None = all countries together
OUTPUT = "my_results"  # results are saved here (next to this script)

# No keyword sheet yet? This writes a template to edit:
# ni.keywords_template(KEYWORDS, countries=COUNTRIES)

# ---- Run -----------------------------------------------------------------------
result = ni.build_index(ARCHIVE, KEYWORDS, COUNTRIES, START, END,
                        index=INDEX, name=NAME, history=HISTORY, gdp=GDP_FILE, gdp_names=GDP_NAMES,
                        groups=GROUPS, output=OUTPUT)
result.show()
