"""Article deduplication within a country-month.

Articles are deduplicated primarily by their link. When the link is missing,
the title and text stand in for it, so two copies of the same story with no
link still collapse to one row.

Two rule sets (see :mod:`CAPEnewsindex._rules`): ``"cape"`` (the default) uses the
keys of CAPE's EPU index -- :func:`cape_canonical_url`, or ``title + text``
(stripped, lower case) for an article without a link; an article with neither
is never treated as a duplicate. ``"legacy"`` uses :func:`canonical_url` and
the normalized title and text.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

from . import _rules
from .match import is_missing, normalize

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def canonical_url(url: object) -> str:
    """Normalize a URL for deduplication: lower-cased scheme/host, no
    fragment, no tracking query parameters, no trailing slash."""
    text = "" if is_missing(url) else str(url).strip()
    if not text:
        return ""
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or ""
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


# --- the CAPE EPU index's keys (rules="cape") ------------------------------------------
# Query parameters that never identify an article (tracking, sharing, comments).
_IGNORED_QUERY = re.compile(
    r"(?i)^(utm_.*|fbclid|gclid|msclkid|mc_[a-z]+|amp|output|ref|ref_src|share|shared|source|"
    r"from|via|replytocom|fb_.*|igshid|s|cn-reloaded|doing_wp_cron|lang|hl)$")
# Pages whose path alone does not identify the article (the article id is in the query).
_SCRIPT_PATH = re.compile(r"(?i)(^/$|\.(php\d?|aspx?|jsp|cfm|cgi|pl|html?)$|/index$)")


def _article_query(path: str, query: str) -> str:
    """'?k=v&...' when the query is what identifies the article (``/?p=48834``), else ''."""
    if not query or not _SCRIPT_PATH.search(path):
        return ""
    parts = []
    for item in query.split("&"):
        if not item:
            continue
        k, _, v = item.partition("=")
        if not _IGNORED_QUERY.match(k):
            parts.append(f"{k}={v}" if v or "=" in item else k)
    return ("?" + "&".join(sorted(parts))) if parts else ""


def cape_canonical_url(url: object) -> str:
    """The CAPE index's link key: host without ``www``, path without repeated or trailing
    slashes, plus the query only where it identifies the article -- all lower case.
    ``""`` for a missing or unreadable link."""
    if is_missing(url):
        return ""
    try:
        parts = urlsplit(str(url).strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/") or "/"
    return f"{host}{path}{_article_query(path, parts.query)}".lower()


def article_key(url: object, title: object, text: object, rules: str = _rules.DEFAULT) -> str:
    """The duplicate key of one article; ``""`` means "never a duplicate".

    ``title``/``text`` are as stored for ``"cape"`` and as read (HTML decoded) for
    ``"legacy"``.
    """
    if _rules.check(rules) == "cape":
        key = cape_canonical_url(url)
        if key:
            return "u" + key
        fallback = ("" if is_missing(title) else str(title)).strip().lower() + "\n" + \
                   ("" if is_missing(text) else str(text)).strip().lower()
        return ("t" + fallback) if fallback.strip() else ""
    key = canonical_url(url)
    return ("u" + key) if key else ("t" + normalize(title) + "\x1f" + normalize(text))


def _hash_blob(blob: str) -> str:
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def dedupe(
    articles: pd.DataFrame,
    *,
    group_cols: tuple[str, ...] = ("country", "year_month"),
    url_col: str = "url",
    title_col: str = "title",
    text_col: str = "text",
    rules: str = _rules.DEFAULT,
) -> pd.DataFrame:
    """Drop duplicate articles within each ``group_cols`` group.

    A row is a duplicate of an earlier row in the same group if they have the
    same :func:`article_key`: the same link, or, for articles without a link,
    the same title and text (``rules`` decides how links and text are
    compared; see the module notes). The first occurrence in the input is
    kept. With ``rules="cape"`` an article with no link, title or text is never
    dropped.
    """
    if articles.empty:
        return articles.copy()
    rules = _rules.check(rules)
    working = articles.copy()
    if "year_month" in group_cols and "year_month" not in working.columns and "date" in working.columns:
        working["year_month"] = working["date"].astype(str).str.slice(0, 7)
    missing_group_cols = [col for col in group_cols if col not in working.columns]
    if missing_group_cols:
        raise KeyError(f"missing grouping column(s): {missing_group_cols}")
    keys = [article_key(u, t, x, rules) for u, t, x in
            zip(working[url_col], working[title_col], working[text_col])]
    working["_dedup_key"] = [_hash_blob(k) if k else "" for k in keys]
    no_key = working["_dedup_key"] == ""
    kept = working[no_key] if rules == "cape" else working.iloc[0:0]
    rest = working[~no_key] if rules == "cape" else working
    rest = rest.drop_duplicates(subset=[*group_cols, "_dedup_key"], keep="first")
    deduped = pd.concat([kept, rest]).sort_index() if len(kept) else rest
    return deduped.drop(columns="_dedup_key").reset_index(drop=True)
