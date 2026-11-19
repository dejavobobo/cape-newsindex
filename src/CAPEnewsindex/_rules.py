"""Which conventions the library follows when it reads, counts and groups articles.

``rules="cape"`` (the default) follows CAPE's own EPU index (EPU_Index_Latest), so the
same archive, keywords and GDP give the same numbers in both:

- the text is matched as stored: HTML codes such as ``&rsquo;`` are not decoded first;
- the newspaper is the newspaper folder and the month is the month folder (not the
  file's ``site`` column or the article's ``date``);
- duplicates within a country-month: the same link (host without ``www``, path, and the
  query only where it identifies the article), or, for an article without a link, the
  same title and text; the first copy is kept, newspapers in name order;
- group indices: a country of the group with GDP but no index that month counts as
  neutral (z = 0) with its usual weight; after a history period the GDP weights stay
  at their value in the history's last month.

``rules="legacy"`` gives the library's results before 18 Nov 2026: HTML codes decoded,
newspaper from the ``site`` column, month from ``date``, duplicates by the full link or
the normalised title and text, a country without an index that month left out of the
group, and each month's own GDP after the history.
"""

from __future__ import annotations

RULES = ("cape", "legacy")
DEFAULT = "cape"


def check(rules: str | None) -> str:
    value = DEFAULT if rules is None else str(rules).strip().lower()
    if value not in RULES:
        raise ValueError(f'rules must be "cape" (the default) or "legacy", not {rules!r}.')
    return value


def describe(rules: str) -> str:
    """One line for the run's printout and the saved settings."""
    if check(rules) == "cape":
        return ("cape (same as the CAPE EPU index: text as stored, newspaper and month from the folders, "
                "link/text duplicates, missing country neutral, GDP frozen after the history)")
    return ("legacy (library rules before 18 Nov 2026: HTML decoded, site/date columns, "
            "missing country left out, GDP of each month)")
