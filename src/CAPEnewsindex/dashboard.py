"""One self-contained HTML dashboard for an :class:`CAPEnewsindex.IndexResult`.

Everything is in the single ``.html`` file (charts are inline SVG), so it
opens in any browser, offline, and can be emailed as one attachment.
Charts need matplotlib (``pip install CAPEnewsindex[plot]``); without it the
dashboard still has every table.
"""

from __future__ import annotations

import datetime
import html
import io

import pandas as pd

from ._version import __version__

_CSS = """
:root { --ink:#1f2933; --muted:#616e7c; --line:#e4e7eb; --bg:#f7f8fa; --card:#fff; --accent:#1f6feb; }
* { box-sizing:border-box; }
body { margin:0; font:14px/1.5 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; color:var(--ink); background:var(--bg); }
header { background:#102a43; color:#fff; padding:24px 32px; }
header h1 { margin:0 0 4px; font-size:22px; }
header p { margin:0; color:#bcccdc; }
main { max-width:1200px; margin:0 auto; padding:24px 32px 48px; }
h2 { font-size:18px; margin:32px 0 12px; }
h3 { font-size:15px; margin:20px 0 8px; color:var(--muted); font-weight:600; }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:12px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px 16px; }
.card .label { color:var(--muted); font-size:12px; }
.card .value { font-size:24px; font-weight:600; }
.card .sub { color:var(--muted); font-size:12px; }
.up { color:#c62828; } .down { color:#2e7d32; }
.panel { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:16px; margin-bottom:16px; overflow-x:auto; }
.grid2 { display:grid; grid-template-columns:repeat(auto-fill,minmax(520px,1fr)); gap:12px; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th, td { padding:6px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
th { color:var(--muted); font-weight:600; background:#fafbfc; position:sticky; top:0; }
.tabs { display:flex; gap:8px; margin:8px 0 16px; }
.tabs button { border:1px solid var(--line); background:#fff; padding:8px 14px; border-radius:6px; cursor:pointer; font:inherit; }
.tabs button.on { background:var(--accent); color:#fff; border-color:var(--accent); }
.version { display:none; } .version.on { display:block; }
.note { color:var(--muted); font-size:13px; }
details summary { cursor:pointer; color:var(--accent); }
svg { width:100%; height:auto; }
.scroll { max-height:420px; overflow:auto; }
"""

_JS = """
function show(v){document.querySelectorAll('.version').forEach(e=>e.classList.toggle('on',e.id===v));
document.querySelectorAll('.tabs button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));}
"""


def _e(text) -> str:
    return html.escape(str(text))


def _table(df: pd.DataFrame, *, index: bool = False, floats: int = 1) -> str:
    if df is None or df.empty:
        return '<p class="note">No rows.</p>'
    if index:  # e.g. months down the side: make them a normal first column
        df = df.reset_index().rename(columns={"year_month": "month", "index": "month"})
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_integer_dtype(df[col]):
            df[col] = df[col].map(lambda v: f"{v:,}")
    return df.to_html(index=False, border=0, float_format=lambda x: f"{x:,.{floats}f}", na_rep="")


def _svg(fig) -> str:
    import matplotlib.pyplot as plt

    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    text = buf.getvalue()
    return text[text.index("<svg"):]


def _line_chart(series: dict[str, pd.DataFrame], title: str, *, y="EPU", ref=100.0, height=3.6, width=11,
                color_index: int | None = None):
    try:
        import matplotlib

        matplotlib.use("Agg", force=False)
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        return '<p class="note">Install matplotlib to see charts: pip install CAPEnewsindex[plot]</p>'
    fig, ax = plt.subplots(figsize=(width, height))
    palette = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for i, (name, g) in enumerate(series.items()):
        g = g.sort_values("year_month")
        x = pd.PeriodIndex(g["year_month"], freq="M").to_timestamp()
        color = palette[(color_index if color_index is not None else i) % len(palette)]
        ax.plot(x, g[y], label=name, color=color, linewidth=1.6,
                marker="o" if len(g) <= 24 else None, markersize=3)
    if ref is not None:
        ax.axhline(ref, color="grey", linewidth=0.8, linestyle=":")
    small = width < 8
    # Numeric dates (2024-01). Small charts get fewer, well-spaced labels.
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=4 if small else 10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    if small:
        ax.tick_params(labelsize=8)
    ax.set_title(title, loc="left", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    if len(series) > 1:
        ax.legend(frameon=False, fontsize=8, ncol=min(4, len(series)))
    return _svg(fig)


def _cards(data: pd.DataFrame, measure: str) -> str:
    out = []
    for name, g in data.groupby("country", sort=True):
        g = g.sort_values("year_month")
        last = float(g[measure].iloc[-1])
        change = ""
        if len(g) > 1:
            d = last - float(g[measure].iloc[-2])
            cls = "up" if d > 0 else "down"
            change = f'<span class="{cls}">{"▲" if d > 0 else "▼"} {abs(d):.1f}</span> vs previous month'
        out.append(
            f'<div class="card"><div class="label">{_e(name)} · {_e(g["year_month"].iloc[-1])}</div>'
            f'<div class="value">{last:.1f}</div><div class="sub">{change}</div></div>'
        )
    return f'<div class="cards">{"".join(out)}</div>'


def _version_section(result, key: str, label: str, data: pd.DataFrame, regions, months: int) -> str:
    if data is None or data.empty:
        return f'<p class="note">No index values for {_e(label)}.</p>'
    m = result.measure
    parts = [f'<h2>Latest values <span class="note">({_e(label)})</span></h2>', _cards(data, m)]
    by_country = {c: g for c, g in data.groupby("country", sort=True)}
    parts.append('<div class="panel">' + _line_chart(by_country, f"{m} index -- {label}", y=m) + "</div>")
    if len(by_country) > 1:
        small = "".join(
            f'<div class="panel">{_line_chart({c: g}, c, y=m, height=3.0, width=6.5, color_index=i)}</div>'
            for i, (c, g) in enumerate(by_country.items())
        )
        parts.append(f'<div class="grid2">{small}</div>')
    parts.append("<h2>Summary</h2><div class=\"panel\">" + _table(result.table(key.replace("_", " "))) + "</div>")
    parts.append(f"<h2>Last {months} months</h2><div class=\"panel\">"
                 + _table(result._wide(data).tail(months), index=True, floats=2) + "</div>")
    if regions is not None:
        if regions.empty:
            parts.append(f'<h2>Group {m}</h2><p class="note">No group series: each country needs 2+ months '
                         "with a changing index in the scaling period.</p>")
        else:
            groups = {g: r for g, r in regions.groupby("group", sort=True)}
            members = regions.groupby("group")["n_countries"].max()
            parts.append(f"<h2>Group {m} (GDP-weighted)</h2><div class=\"panel\">"
                         + _line_chart(groups, f"{m} by group of countries", y="index") + "</div>")
            parts.append('<p class="note">Countries per group: '
                         + ", ".join(f"{_e(g)} ({int(n)})" for g, n in members.items()) + "</p>")
            wide = regions.pivot(index="year_month", columns="group", values="index")
            wide.columns.name = None
            parts.append('<div class="panel scroll">' + _table(wide.tail(months), index=True) + "</div>")
    parts.append(f"<details><summary>All months ({len(data):,} rows)</summary><div class=\"panel scroll\">"
                 + _table(data, floats=3) + "</div></details>")
    return "\n".join(parts)


def _coverage(result, start: str, end: str) -> str:
    m = result.measure
    hits = f"{m.lower()}_articles"
    c = result.counts
    c = c[(c["year_month"] >= start) & (c["year_month"] <= end)]
    if c.empty:
        return '<p class="note">No articles in this period.</p>'
    per_country = c.groupby("country").agg(
        newspapers=("site", "nunique"), months=("year_month", "nunique"),
        articles=("all_articles", "sum"), **{hits: (hits, "sum")},
    ).reset_index()
    per_country[f"{m} share %"] = 100 * per_country[hits] / per_country["articles"]
    per_site = c.groupby(["country", "site"]).agg(
        months=("year_month", "nunique"), first=("year_month", "min"), last=("year_month", "max"),
        articles=("all_articles", "sum"), **{hits: (hits, "sum")},
    ).reset_index()
    per_site[f"{m} share %"] = 100 * per_site[hits] / per_site["articles"]
    monthly = c.groupby(["country", "year_month"]).agg(articles=("all_articles", "sum")).reset_index()
    chart = _line_chart(dict(iter(monthly.groupby("country"))),
                        "Articles per month (after removing duplicates)", y="articles", ref=None, height=3)
    return ("<div class=\"panel\">" + _table(per_country) + "</div>"
            + "<div class=\"panel\">" + chart + "</div>"
            + "<h3>Newspapers</h3><div class=\"panel scroll\">" + _table(per_site) + "</div>")


def _keywords(result) -> str:
    kw = result.keywords
    if kw is None or kw.empty:
        return '<p class="note">No keyword list stored.</p>'
    counts = kw.groupby(["country", "group"]).size().unstack(fill_value=0).reset_index()
    counts.columns.name = None
    lists = []
    group_names = list(dict.fromkeys(kw["group"]))
    for country, g in kw.groupby("country", sort=True):
        cells = "".join(
            f"<td style='text-align:left;white-space:normal'>{_e(', '.join(g[g['group'] == grp]['term']))}</td>"
            for grp in group_names
        )
        lists.append(f"<tr><td>{_e(country)}</td>{cells}</tr>")
    heads = "".join(f"<th style='text-align:left'>{_e(grp)}</th>" for grp in group_names)
    full = f"<table><tr><th>country</th>{heads}</tr>" + "".join(lists) + "</table>"
    return ("<div class=\"panel\">" + _table(counts) + "</div>"
            + f"<details><summary>Every term used ({len(kw):,})</summary><div class=\"panel scroll\">{full}</div></details>")


def build(result, months: int = 12, version: str = "both") -> str:
    """The dashboard as one HTML string."""
    s = result.settings
    start, end = s["period"].split("..")
    versions = result._versions(version)
    today = datetime.date.today().isoformat()

    tabs = ""
    if len(versions) > 1:
        tabs = '<div class="tabs">' + "".join(
            f'<button data-v="{key}" class="{"on" if i == 0 else ""}" onclick="show(\'{key}\')">{_e(label)}</button>'
            for i, (key, label, _d, _r) in enumerate(versions)
        ) + "</div>"
    sections = "".join(
        f'<div class="version{" on" if i == 0 else ""}" id="{key}">'
        + _version_section(result, key, label, data, regions, months) + "</div>"
        for i, (key, label, data, regions) in enumerate(versions)
    )
    method = (
        "<p><b>With history</b>: each newspaper's scaling and the country mean are fixed on the history "
        "period, so 100 = the history average and past values never change when new months are added. "
        "<b>No history</b>: scaled on the months shown, so 100 = their average; values shift when the "
        f"period changes. Method: Baker, Bloom and Davis (2016) -- an article counts for the {_e(result.measure)} "
        f"index when it contains at least one term from each keyword group: "
        f"{_e(', '.join(s.get('keyword_groups', ['economic', 'policy', 'uncertainty'])))}.</p>"
    )
    skipped = ""
    if len(result.skipped_files):
        skipped = ("<h2>Files that could not be read</h2><div class=\"panel scroll\">"
                   + _table(result.skipped_files) + "</div>")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(result.measure)} dashboard {_e(s['period'])}</title><style>{_CSS}</style><script>{_JS}</script></head>
<body>
<header><h1>{_e(s.get('title', 'Economic Policy Uncertainty'))} dashboard</h1>
<p>{_e(', '.join(s['countries']))} · {_e(s['period'])} · {_e(s['mode'])} · made {today} with CAPEnewsindex {__version__}</p></header>
<main>
{tabs}
{sections}
<h2>Articles and newspapers</h2>
{_coverage(result, start, end)}
<h2>Keywords used</h2>
{_keywords(result)}
{skipped}
<h2>How to read this</h2>
<div class="panel note">{method}</div>
</main></body></html>"""


def write(result, path, months: int = 12, version: str = "both"):
    from pathlib import Path

    path = Path(path)
    path.write_text(build(result, months=months, version=version), encoding="utf-8")
    return path
