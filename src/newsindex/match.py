"""Unicode-aware literal term matching and EPU classification.

Terms are matched as complete lexical units, not arbitrary substrings. This
prevents abbreviations such as EAC, EU, and OMC from matching inside longer
words, while whole phrases, apostrophes, hyphens, Arabic, and Ethiopic text
are matched correctly. Word boundaries are determined from the Unicode
general category of each character (letters, numbers, and combining marks
count as word characters), so the same logic works for scripts that do not
use ASCII word-boundary conventions.
"""

from __future__ import annotations

import functools
import math
import re
import unicodedata
from typing import Iterable, Mapping, Sequence

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'"})
_DASHES = str.maketrans(
    {
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)


_FOLD = {**_APOSTROPHES, **_DASHES}
# (character, replacement) pairs: replacing only the characters actually present
# gives the same result as str.translate(_FOLD), and is far faster on long text.
_FOLD_PAIRS = tuple((chr(source), target) for source, target in _FOLD.items())


def _fold(text: str) -> str:
    for source, target in _FOLD_PAIRS:
        if source in text:
            text = text.replace(source, target)
    return text


def is_missing(value: object) -> bool:
    """True for ``None`` and for float NaN (e.g. a missing value read from a
    pandas column), the two ways "no value" shows up in article data."""
    return value is None or (isinstance(value, float) and math.isnan(value))


def normalize(value: object) -> str:
    """Return stable Unicode text used for both dictionary terms and articles.

    Applies Unicode NFKC normalization, folds apostrophe and dash variants to
    a single form, collapses whitespace, and case-folds the result.
    """
    text = "" if is_missing(value) else str(value)
    if not text.isascii() and not unicodedata.is_normalized("NFKC", text):
        text = unicodedata.normalize("NFKC", text)
    # str.split() splits on exactly the characters re's \s matches and drops
    # leading/trailing runs: same result as re.sub(r"\s+", " ", ...).strip(),
    # several times faster on article-length text.
    return " ".join(_fold(text).split()).casefold()


def _is_word_character(character: str) -> bool:
    if not character:
        return False
    return unicodedata.category(character)[0] in {"L", "N", "M"}


def _term_body(normalized: str) -> str:
    """The escaped, separator-flexible middle of a term's pattern: its
    words joined by ``(?:-|\\s)+`` so a dash and a space are interchangeable
    between them, same as :func:`normalize` already folds dash variants and
    collapses whitespace within a single string. No boundary assertions."""
    pieces = re.split(r"([\s-]+)", normalized)
    body_parts: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        if re.fullmatch(r"[\s-]+", piece):
            body_parts.append(r"(?:-|\s)+")
        else:
            body_parts.append(re.escape(piece))
    return "".join(body_parts)


@functools.lru_cache(maxsize=32768)
def _compiled_term(term: str) -> re.Pattern[str]:
    normalized = normalize(term)
    if not normalized:
        return re.compile(r"(?!x)x")
    body = _term_body(normalized)
    left = r"(?<![^\W_])" if _is_word_character(normalized[0]) else ""
    right = r"(?![^\W_])" if _is_word_character(normalized[-1]) else ""
    return re.compile(left + body + right, flags=re.UNICODE)


def term_matches(normalized_text: str, term: str) -> bool:
    """Match one term against text already returned by :func:`normalize`."""
    return bool(_compiled_term(term).search(normalized_text))


def find_terms(text: object, terms: Iterable[str]) -> list[str]:
    """Return each distinct dictionary term found in ``text``, in input order."""
    normalized = normalize(text)
    seen: set[str] = set()
    matches: list[str] = []
    for value in terms:
        term = str(value).strip()
        key = normalize(term)
        if term and key not in seen and term_matches(normalized, term):
            seen.add(key)
            matches.append(term)
    return matches


def any_term_matches(text: object, terms: Iterable[str]) -> bool:
    """True if at least one of ``terms`` occurs in ``text``."""
    normalized = normalize(text)
    return any(term_matches(normalized, str(term)) for term in terms if str(term).strip())


def component_matches(
    title: object, body: object, components: Mapping[str, Sequence[str]]
) -> dict[str, bool]:
    """Return, for each named component, whether any of its terms occur."""
    full_text = f"{'' if is_missing(title) else title} {'' if is_missing(body) else body}"
    normalized = normalize(full_text)
    return {
        name: any(
            term_matches(normalized, str(term)) for term in terms if str(term).strip()
        )
        for name, terms in components.items()
    }


@functools.lru_cache(maxsize=4096)
def _combined_pattern(terms: tuple[str, ...]) -> re.Pattern[str]:
    bodies: list[str] = []
    seen: set[str] = set()
    for term in terms:
        term = str(term).strip()
        if not term:
            continue
        key = normalize(term)
        if key in seen:
            continue
        compiled = _compiled_term(term)
        if compiled.pattern == r"(?!x)x":
            continue
        seen.add(key)
        bodies.append(compiled.pattern)
    if not bodies:
        return re.compile(r"(?!x)x")
    return re.compile("|".join(f"(?:{body})" for body in bodies), flags=re.UNICODE)


def component_pattern(terms: Sequence[str]) -> re.Pattern[str]:
    """One compiled regex matching normalized text that contains any of ``terms``.

    Equivalent to ``any(term_matches(text, term) for term in terms)`` but as
    a single precompiled alternation, so a whole column of articles can be
    tested against a component in one vectorized pass (e.g. pandas
    ``Series.str.contains``) instead of one Python-level call per term per
    row. Memoized per distinct ``terms`` tuple, since the same dictionary
    component is reused across every row and batch of a run.

    This is the reference definition of a component match; for classifying
    many articles, :class:`EPUMatcher` gives the same answers much faster.
    """
    return _combined_pattern(tuple(terms))


def is_epu(
    title: object,
    body: object,
    economic_terms: Sequence[str],
    policy_terms: Sequence[str],
    uncertainty_terms: Sequence[str],
) -> bool:
    """True if the article contains at least one Economic, Policy, and
    Uncertainty term (Baker, Bloom and Davis, 2016 classification rule)."""
    components = {
        "economic": economic_terms,
        "policy": policy_terms,
        "uncertainty": uncertainty_terms,
    }
    flags = component_matches(title, body, components)
    return flags["economic"] and flags["policy"] and flags["uncertainty"]


# ---------------------------------------------------------------------------
# Fast classification
# ---------------------------------------------------------------------------
# The functions below give exactly the same yes/no answer as
# ``component_pattern(terms).search(normalize(text))`` but are several times
# faster on real articles:
#
# * :func:`light_normalize` does everything :func:`normalize` does except
#   collapsing whitespace. That step cannot change a match: a term's literal
#   pieces never contain whitespace, its separators already accept any run of
#   whitespace/dashes, and a whitespace character is a non-word character for
#   the boundary checks whether or not it was collapsed.
# * :class:`ComponentMatcher` tests each term's literal pieces with plain
#   substring checks (C speed) and only runs the term's boundary-checked
#   pattern when all of them are present -- and then only at positions where
#   the term's first piece occurs. Terms that hit are moved forward, so the
#   frequent ones are tried first.


def light_normalize(value: object) -> str:
    """:func:`normalize` without whitespace collapsing (see note above)."""
    text = "" if is_missing(value) else str(value)
    if text.isascii():
        text = text.lower()
        return text.replace("`", "'") if "`" in text else text
    if not unicodedata.is_normalized("NFKC", text):
        text = unicodedata.normalize("NFKC", text)
    return _fold(text).casefold()


_SEPARATOR_RUN = re.compile(r"[\s-]+")
_LEAD = re.compile(r"[^\s-]*")


class _Term:
    __slots__ = ("pieces", "lead", "match", "search")

    def __init__(self, normalized: str, pattern: re.Pattern[str]):
        self.pieces = tuple(
            sorted((p for p in _SEPARATOR_RUN.split(normalized) if p), key=len, reverse=True)
        )
        self.lead = _LEAD.match(normalized).group(0)
        self.match = pattern.match
        self.search = pattern.search


class ComponentMatcher:
    """True if text (from :func:`light_normalize`) contains any of ``terms``.

    Same answer as ``component_pattern(terms).search(normalize(text))``.
    """

    def __init__(self, terms: Iterable[str]):
        self.terms: list[_Term] = []
        seen: set[str] = set()
        for value in terms:
            term = str(value).strip()
            if not term:
                continue
            key = normalize(term)
            if not key or key in seen:
                continue
            seen.add(key)
            self.terms.append(_Term(key, _compiled_term(term)))

    def __bool__(self) -> bool:
        return bool(self.terms)

    def __call__(self, text: str) -> bool:
        terms = self.terms
        for i, t in enumerate(terms):
            for piece in t.pieces:
                if piece not in text:
                    break
            else:
                hit = False
                lead = t.lead
                if lead:
                    match = t.match
                    pos = text.find(lead)
                    while pos != -1:
                        if match(text, pos):
                            hit = True
                            break
                        pos = text.find(lead, pos + 1)
                else:
                    hit = t.search(text) is not None
                if hit:
                    if i:  # move frequent terms forward
                        terms[i - 1], terms[i] = t, terms[i - 1]
                    return True
        return False


_WORD_RUN = re.compile(r"[^\W_]+")
# For ASCII text, [^\W_] is exactly [A-Za-z0-9]: map everything else to a space and split.
_ASCII_NONWORD = {c: " " for c in range(128) if not chr(c).isalnum()}


def word_tokens(text: str) -> frozenset[str]:
    """Maximal runs of word characters -- the units the term boundaries see."""
    if text.isascii():
        return frozenset(text.translate(_ASCII_NONWORD).split())
    return frozenset(_WORD_RUN.findall(text))


class TokenComponentMatcher:
    """Same answer as :class:`ComponentMatcher`, faster for long term lists.

    A boundary-checked single word matches exactly when it is one of the
    text's maximal word runs, so those terms are a set lookup. A phrase can
    only match when every word run inside it is also one of the text's word
    runs, so its pattern is only tried for the few phrases that pass that
    check. Cost is one tokenization per article (shared by all components)
    instead of one substring scan per term.
    """

    def __init__(self, terms: Iterable[str]):
        self.single: set[str] = set()
        self.by_anchor: dict[str, list[tuple[frozenset[str], re.Pattern[str]]]] = {}
        self.unanchored: list[re.Pattern[str]] = []
        seen: set[str] = set()
        for value in terms:
            term = str(value).strip()
            if not term:
                continue
            key = normalize(term)
            if not key or key in seen:
                continue
            seen.add(key)
            first_ok, last_ok = _is_word_character(key[0]), _is_word_character(key[-1])
            if _WORD_RUN.fullmatch(key) and first_ok and last_ok:
                self.single.add(key)
                continue
            required = _WORD_RUN.findall(key)
            # A run at the term's edge is only bounded if that edge has a boundary check.
            if required and _WORD_RUN.match(key) and not first_ok:
                required = required[1:]
            if required and _WORD_RUN.fullmatch(key[-1]) and not last_ok:
                required = required[:-1]
            pattern = _compiled_term(term)
            if not required:
                self.unanchored.append(pattern)
                continue
            anchor = max(required, key=len)
            self.by_anchor.setdefault(anchor, []).append((frozenset(required), pattern))
        self.size = len(seen)

    def __bool__(self) -> bool:
        return self.size > 0

    def __call__(self, text: str, tokens: frozenset[str]) -> bool:
        if not self.single.isdisjoint(tokens):
            return True
        for anchor in self.by_anchor.keys() & tokens:
            for required, pattern in self.by_anchor[anchor]:
                if required <= tokens and pattern.search(text):
                    return True
        return any(p.search(text) for p in self.unanchored)


#: Components with more distinct terms than this use :class:`TokenComponentMatcher`.
TOKEN_MATCHER_MIN_TERMS = 40


class IndexMatcher:
    """True when a text contains at least one term from *every* group.

    ``IndexMatcher([economic_terms, policy_terms, uncertainty_terms])`` is the
    EPU rule; any two or more groups work the same way (TPU, ETU, ...).
    """

    def __init__(self, groups: Sequence[Sequence[str]]):
        groups = list(groups)
        if len(groups) < 2:
            raise ValueError("An index needs at least two keyword groups.")
        components = []
        for terms in groups:
            simple = ComponentMatcher(terms)
            if len(simple.terms) > TOKEN_MATCHER_MIN_TERMS:
                components.append((True, TokenComponentMatcher(terms)))
            else:
                components.append((False, simple))
        self.components = tuple(components)
        self.empty = not all(c for _, c in self.components)

    def __call__(self, light_normalized_text: str) -> bool:
        if self.empty:
            return False
        tokens = None
        for uses_tokens, component in self.components:
            if uses_tokens:
                if tokens is None:
                    tokens = word_tokens(light_normalized_text)
                hit = component(light_normalized_text, tokens)
            else:
                hit = component(light_normalized_text)
            if not hit:
                return False
        return True

    def matches(self, title: object, body: object) -> bool:
        t = "" if is_missing(title) else str(title)
        b = "" if is_missing(body) else str(body)
        return self(light_normalize(f"{t} {b}"))

    is_epu = matches


class EPUMatcher(IndexMatcher):
    """:class:`IndexMatcher` for economic, policy and uncertainty terms."""

    def __init__(self, economic_terms, policy_terms, uncertainty_terms):
        super().__init__([economic_terms, policy_terms, uncertainty_terms])
