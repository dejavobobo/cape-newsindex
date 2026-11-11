"""Keyword dictionaries: one set of keyword groups per country.

A dictionary maps each country to named keyword groups -- ``economic``,
``policy``, ``uncertainty``, ``trade``, ``energy``, or any group you name
yourself. An index is defined by the groups it requires: an article counts
when it contains at least one term from *every* required group (EPU =
economic + policy + uncertainty; TPU = trade + policy + uncertainty; ...).

Keywords can be read from Excel / CSV (columns ``country``, ``group``,
``term``), a plain-text file, JSON (simple or the EPTU schema with
``ECONOMY_TERMS``-style keys), or a Python dict -- see :func:`read`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .match import normalize

#: The groups used by the EPU index.
EPU_GROUPS = ("economic", "policy", "uncertainty")

#: Short or alternative spellings accepted for group names.
_ALIASES = {"economy": "economic", "econ": "economic", "e": "economic", "p": "policy",
            "u": "uncertainty", "t": "trade", "eg": "energy"}
_GROUP_NAME = re.compile(r"^[^\W\d][\w \-]{0,40}$")


def group_name(name: object) -> str:
    """Normalise a keyword-group name: lower case, ``ECONOMY_TERMS`` -> ``economic``."""
    key = " ".join(str(name).strip().lower().replace("_", " ").split())
    if key.endswith(" terms"):
        key = key[: -len(" terms")]
    key = _ALIASES.get(key, key).replace(" ", "_")
    if not key or not _GROUP_NAME.match(key):
        raise ValueError(f"{name!r} is not a usable keyword group name (use words like economic, policy, uncertainty).")
    return key


@dataclass(frozen=True)
class CountryDictionary:
    """One country's keyword groups, e.g. ``{"economic": (...), "policy": (...)}``."""

    country: str
    groups: dict[str, tuple[str, ...]] = field(default_factory=dict)
    languages: tuple[str, ...] = ()

    def terms(self, group: str) -> tuple[str, ...]:
        """Terms of one group (empty if the country has none)."""
        return self.groups.get(group_name(group), ())

    # The standard groups, as attributes.
    @property
    def economic(self) -> tuple[str, ...]:
        return self.terms("economic")

    @property
    def policy(self) -> tuple[str, ...]:
        return self.terms("policy")

    @property
    def uncertainty(self) -> tuple[str, ...]:
        return self.terms("uncertainty")

    @property
    def trade(self) -> tuple[str, ...]:
        return self.terms("trade")

    @property
    def energy(self) -> tuple[str, ...]:
        return self.terms("energy")


@dataclass(frozen=True)
class Dictionary:
    """Keyword groups for each country."""

    countries: dict[str, CountryDictionary]
    schema: str = ""
    source: Path | None = None
    meta: dict = field(default_factory=dict)

    def __getitem__(self, country: str) -> CountryDictionary:
        return self.countries[country]

    def __contains__(self, country: str) -> bool:
        return country in self.countries

    def for_countries(self, names) -> "Dictionary":
        """The keywords for these countries, using the ``*`` (every country) terms
        for any country without its own entry."""
        shared = self.countries.get("*")
        if shared is None:
            return self
        import dataclasses

        picked = {str(n): self.countries.get(str(n), shared) for n in names}
        return dataclasses.replace(self, countries=picked)

    def __iter__(self):
        return iter(self.countries)

    def __len__(self) -> int:
        return len(self.countries)

    @property
    def group_names(self) -> list[str]:
        """Every group name used by any country, in first-seen order."""
        names: dict[str, None] = {}
        for entry in self.countries.values():
            names.update(dict.fromkeys(entry.groups))
        return list(names)


#: The keyword template shipped with the package: CAPE's production dictionary
#: (54 African countries; economic, policy, uncertainty and trade terms). It is
#: only used when you ask for it -- :func:`template` writes it out for you to
#: edit -- never as a silent default.
TEMPLATE_PATH = Path(__file__).resolve().parent / "data" / "eptu_country_keywords.json"


def _clean(values) -> tuple[str, ...]:
    seen, out = set(), []
    for v in values or []:
        s = "" if v is None else str(v).strip()
        if s and s.lower() != "nan" and s not in seen:
            seen.add(s)
            out.append(s)
    return tuple(out)


def _build(rows: dict[str, dict[str, list[str]]], source=None, **extra) -> Dictionary:
    countries: dict[str, CountryDictionary] = {}
    for country, groups in rows.items():
        name = str(country).strip()
        languages = tuple(groups.get("languages", ()))
        cleaned = {g: _clean(v) for g, v in groups.items() if g != "languages"}
        countries[name] = CountryDictionary(
            country=name, groups={g: v for g, v in cleaned.items() if v}, languages=languages
        )
    return Dictionary(countries=countries, source=source, **extra)


def _add_shared(rows: dict, shared: dict | None) -> None:
    """Terms given for country ``*`` (or ``all``) are added to every country."""
    if shared:
        for groups in rows.values():
            for g, terms in shared.items():
                groups[g] = list(groups.get(g, [])) + list(terms)


def load(path: str | Path) -> Dictionary:
    """Load an EPTU-schema JSON file (keys like ``ECONOMY_TERMS``, ``ENERGY_TERMS``).

    Every ``*_TERMS`` list becomes a group. (The bundled template is
    ``load(TEMPLATE_PATH)``.)
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("countries", raw)
    rows = {}
    for country, payload in entries.items():
        if str(country).startswith("_") or not isinstance(payload, dict):
            continue
        groups = {group_name(k): v for k, v in payload.items() if str(k).upper().endswith("_TERMS")}
        groups["languages"] = payload.get("languages", [])
        rows[country] = groups
    meta = raw.get("_meta", {}) if isinstance(raw, dict) else {}
    return _build(rows, source=path, schema=meta.get("schema", ""), meta=meta)


def validate(dictionary: Dictionary, groups=EPU_GROUPS) -> list[dict]:
    """Audit a dictionary for empty groups and terms shared between groups.

    Returns a list of issue rows (empty if clean). A term that normalizes to
    the same text in two of ``groups`` would let one word satisfy two
    requirements, which the index method does not allow.
    """
    groups = [group_name(g) for g in groups]
    issues: list[dict] = []
    for country, entry in dictionary.countries.items():
        for name in groups:
            if not entry.terms(name):
                issues.append({"country": country, "issue": "empty_component", "component": name})
        normalized = {name: {normalize(t) for t in entry.terms(name) if str(t).strip()} for name in groups}
        for i, left in enumerate(groups):
            for right in groups[i + 1:]:
                overlap = normalized[left] & normalized[right]
                if overlap:
                    issues.append({
                        "country": country,
                        "issue": "cross_component_overlap",
                        "components": f"{left}/{right}",
                        "terms": sorted(overlap),
                    })
    return issues


def fingerprint(dictionary: Dictionary) -> str:
    """A stable hash of the exact dictionary contents.

    Same countries, languages and terms (in any order) give the same value;
    any change gives a different one. Saved histories record it so a later,
    differently worded dictionary is noticed.
    """
    canonical = {
        country: {"languages": sorted(entry.languages),
                  **{g: sorted(normalize(t) for t in terms) for g, terms in sorted(entry.groups.items())}}
        for country, entry in sorted(dictionary.countries.items())
    }
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Plain formats: a sheet, a Python dict, a text file, JSON
# ---------------------------------------------------------------------------
def from_table(table, *, source=None) -> Dictionary:
    """Keywords from a table with columns ``country``, ``group`` and ``term``,
    one term per row. A row whose country is ``*`` (or ``all``) applies to
    every country in the table."""
    import pandas as pd

    cols = {str(c).strip().lower(): c for c in table.columns}
    country_col = cols.get("country")
    group_col = next((cols[c] for c in ("group", "component", "category", "type") if c in cols), None)
    term_col = next((cols[c] for c in ("term", "keyword", "word", "phrase") if c in cols), None)
    if country_col is None or group_col is None or term_col is None:
        raise ValueError(
            "The keyword sheet needs three columns: country, group, term "
            f"(group = economic / policy / uncertainty / ...). Columns found: {list(table.columns)}"
        )
    rows: dict[str, dict[str, list[str]]] = {}
    shared: dict[str, list[str]] = {}
    for country, group, term in zip(table[country_col], table[group_col], table[term_col]):
        if pd.isna(term) or pd.isna(group) or str(term).strip() == "":
            continue
        name = "" if pd.isna(country) else str(country).strip()
        target = shared if name.lower() in ("*", "all", "") else rows.setdefault(name, {})
        target.setdefault(group_name(group), []).append(str(term))
    if not rows:
        raise ValueError("The keyword sheet has no country rows (country = * only applies to named countries).")
    _add_shared(rows, shared)
    return _build(rows, source=source)


def from_dict(data: dict) -> Dictionary:
    """Keywords from a Python dict: per country --
    ``{"Nigeria": {"economic": [...], "policy": [...], "uncertainty": [...]}}`` --
    or one set of groups for every country -- ``{"economic": [...], ...}``
    (stored under the country ``"*"``)."""
    if not isinstance(data, dict) or not data:
        raise ValueError("Keywords must be a non-empty dict.")
    if all(isinstance(v, (list, tuple)) for v in data.values()):  # same groups for every country
        return _build({"*": {group_name(k): v for k, v in data.items()}})
    rows = {}
    for country, groups in data.items():
        if not isinstance(groups, dict):
            raise ValueError(
                f"Keywords for {country!r} must be a dict like {{'economic': [...], 'policy': [...], 'uncertainty': [...]}}."
            )
        rows[country] = {(k if k == "languages" else group_name(k)): v for k, v in groups.items()}
    return _build(rows)


_KNOWN_GROUPS = EPU_GROUPS + ("trade", "energy")
_TXT_HEADER = re.compile(r"^\s*([^\W\d][\w \-]{0,40}?)\s*:\s*(.*)$")


def from_text(text: str, *, source=None) -> Dictionary:
    """Keywords from the plain-text format -- one term per line::

        # Lines starting with # are comments.
        [Nigeria]
        economic:
        economy
        exchange rate

        policy:
        central bank

        uncertainty:
        risk

        [*]                 <- terms here are added to every country
        uncertainty:
        volatility

    A group starts with its name and a colon (``economic:``, ``trade:``,
    ``energy:``, or any name of your own). ``policy: central bank`` on one
    line also works for a single term.
    """
    rows: dict[str, dict[str, list[str]]] = {}
    country = group = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            country, group = line[1:-1].strip(), None
            if not country:
                raise ValueError(f"Line {number}: empty country name in brackets.")
            rows.setdefault(country, {})
            continue
        header = _TXT_HEADER.match(line)
        # "name:" alone starts a group; "economic: inflation" (a known group name) adds one term.
        if header and (not header.group(2).strip() or group_name(header.group(1)) in _KNOWN_GROUPS):
            if country is None:
                raise ValueError(f"Line {number}: put a [Country] line before {header.group(1)!r}.")
            group = group_name(header.group(1))
            rows[country].setdefault(group, [])
            if header.group(2).strip():
                rows[country][group].append(header.group(2).strip())
            continue
        if country is None or group is None:
            raise ValueError(
                f"Line {number}: {line!r} comes before a [Country] line and a group line such as 'economic:'."
            )
        rows[country][group].append(line)
    shared = rows.pop("*", None) or rows.pop("all", None)
    if not rows:
        raise ValueError("The keyword file has no [Country] sections.")
    _add_shared(rows, shared)
    return _build(rows, source=source)


def to_text(dictionary: Dictionary, countries=None, groups=None) -> str:
    lines = [
        "# Keywords: one [Country] section each, then one line per group ('economic:',",
        "# 'policy:', 'uncertainty:', 'trade:', ...), each followed by its terms, one per line.",
        "# A [*] section adds its terms to every country.",
        "",
    ]
    for country, entry in dictionary.countries.items():
        if countries is not None and country not in countries:
            continue
        lines.append(f"[{country}]")
        for g in (groups or entry.groups):
            lines.append(f"{g}:")
            lines.extend(entry.terms(g))
            lines.append("")
    return "\n".join(lines)


def _read_json(path: Path) -> Dictionary:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("countries", raw) if isinstance(raw, dict) else raw
    if not isinstance(rows, dict):
        raise ValueError(f"{path.name}: expected a JSON object of countries.")
    entries = {k: v for k, v in rows.items() if not str(k).startswith("_")}
    eptu = any(isinstance(v, dict) and any(str(g).upper().endswith("_TERMS") for g in v) for v in entries.values())
    if eptu:
        return load(path)  # EPTU schema (ECONOMY_TERMS, POLICY_TERMS, ...)
    d = from_dict(entries)
    return Dictionary(countries=d.countries, source=path)


def read(keywords) -> Dictionary:
    """Keywords from any supported form: a :class:`Dictionary`, a dict, a
    DataFrame, or a path to a ``.xlsx``/``.xls``, ``.csv``, ``.txt`` or
    ``.json`` keyword file."""
    import pandas as pd

    if isinstance(keywords, Dictionary):
        return keywords
    if isinstance(keywords, dict):
        return from_dict(keywords)
    if isinstance(keywords, pd.DataFrame):
        return from_table(keywords)
    path = Path(keywords)
    if not path.exists():
        raise FileNotFoundError(f"Keyword file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _read_json(path)
    if suffix in (".xlsx", ".xls"):
        return from_table(pd.read_excel(path), source=path)
    if suffix == ".csv":
        return from_table(pd.read_csv(path, encoding="utf-8-sig"), source=path)
    if suffix == ".txt":
        return from_text(path.read_text(encoding="utf-8-sig"), source=path)
    raise ValueError(f"Keyword file must be .xlsx, .csv, .txt or .json (got {path.name}).")


def to_table(dictionary: Dictionary, countries=None, groups=None) -> "pd.DataFrame":
    """All keywords as one readable table: country, group, term."""
    import pandas as pd

    rows = []
    for country, entry in dictionary.countries.items():
        if countries is not None and country not in countries:
            continue
        for group in (groups or entry.groups):
            rows.extend({"country": country, "group": group, "term": t} for t in entry.terms(group))
    return pd.DataFrame(rows, columns=["country", "group", "term"])


#: Keyword file formats :func:`template` can write and :func:`read` can read.
FORMATS = (".xlsx", ".csv", ".txt", ".json")


def save_keywords(dictionary: Dictionary, path: str | Path, countries=None, groups=None) -> Path:
    """Write keywords to ``path``; the format follows its extension
    (``.xlsx``, ``.csv``, ``.txt`` or ``.json``). ``groups`` limits which
    groups are written (default: all)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in FORMATS:
        raise ValueError(f"Choose a keyword file format: {', '.join(FORMATS)} (got {path.name!r}).")
    groups = [group_name(g) for g in groups] if groups else None
    table = to_table(dictionary, countries=countries, groups=groups)
    if suffix == ".csv":
        table.to_csv(path, index=False, encoding="utf-8-sig")
    elif suffix == ".xlsx":
        table.to_excel(path, index=False, sheet_name="keywords")
    elif suffix == ".txt":
        path.write_text(to_text(dictionary, countries=countries, groups=groups), encoding="utf-8")
    else:
        data = {c: {g: list(e.terms(g)) for g in (groups or e.groups)}
                for c, e in dictionary.countries.items() if countries is None or c in countries}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def template(path: str | Path = "my_keywords.xlsx", countries=None, groups=None) -> Path:
    """Write the bundled keyword template as an editable file to start from.

    Pick the format with the extension: ``.xlsx`` (Excel), ``.csv``, ``.txt``
    or ``.json``. The template is CAPE's production dictionary (54 African
    countries; economic, policy, uncertainty and trade terms): replace or add
    countries and groups (e.g. energy) for your own work.
    ``countries`` / ``groups`` limit what is written (default: everything).
    """
    path = save_keywords(load(TEMPLATE_PATH), path, countries=countries, groups=groups)
    n = len(to_table(load(TEMPLATE_PATH), countries=countries, groups=[group_name(g) for g in groups] if groups else None))
    print(f"Keyword template written to {path.resolve()} ({n:,} terms). Edit it, then pass it as keywords=.")
    return path
