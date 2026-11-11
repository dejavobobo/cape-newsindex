"""One self-contained HTML dashboard for an :class:`CAPEnewsindex.IndexResult`.

The dashboard has separate pages -- Overview, Regions (one chart per group
of countries), Countries (one chart per country, organised by region),
Newspapers, Keywords and About -- and a switch between the with-history
and no-history versions.

Everything is in the single ``.html`` file: the data is embedded and the
charts are drawn by a few lines of plain JavaScript, so the file opens in
any browser, offline, needs no extra Python packages, and can be emailed
as one attachment.
"""

from __future__ import annotations

import datetime
import html
import json

import pandas as pd

from ._version import __version__

#: Credit shown at the bottom of every dashboard.
CREDIT = "CAPE Economic Research and Consulting"
_LOGO_FILES = ("logo.svg", "logo.png", "logo.jpg", "logo.jpeg")

#: Colours for groups of countries; each country takes its group's colour.
_PALETTE = ("#1f6feb", "#d1495b", "#2a9d8f", "#e9a23b", "#7b4fd6", "#3d5a80", "#c05299", "#5c946e",
            "#8d6e63", "#00838f")
_OTHER = "#52606d"

_CSS = """
:root { --ink:#1f2933; --muted:#616e7c; --line:#e4e7eb; --bg:#f5f7fa; --card:#fff; --accent:#1f6feb; --head:#102a43; }
* { box-sizing:border-box; }
body { margin:0; font:14px/1.5 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; color:var(--ink); background:var(--bg); }
header { background:var(--head); color:#fff; padding:22px 32px 0; }
header h1 { margin:0 0 4px; font-size:22px; }
header p { margin:0 0 14px; color:#bcccdc; font-size:13px; }
nav { display:flex; flex-wrap:wrap; gap:4px; align-items:flex-end; }
nav a { color:#d9e2ec; text-decoration:none; padding:9px 16px; border-radius:6px 6px 0 0; font-weight:500; }
nav a:hover { background:rgba(255,255,255,.08); }
nav a.on { background:var(--bg); color:var(--ink); }
.bar { max-width:1240px; margin:0 auto; padding:16px 32px 0; display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; }
.switch { display:inline-flex; border:1px solid var(--line); border-radius:8px; overflow:hidden; background:#fff; }
.switch button { border:0; background:#fff; padding:7px 14px; cursor:pointer; font:inherit; color:var(--muted); }
.switch button.on { background:var(--accent); color:#fff; }
.versionlabel { color:var(--muted); font-size:13px; }
main { max-width:1240px; margin:0 auto; padding:8px 32px 48px; }
.page { display:none; } .page.on { display:block; }
h2 { font-size:18px; margin:26px 0 12px; }
h3 { font-size:16px; margin:28px 0 10px; display:flex; align-items:center; gap:8px; }
h3 .dot { width:12px; height:12px; border-radius:50%; display:inline-block; }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:10px; }
.card { background:var(--card); border:1px solid var(--line); border-left:4px solid var(--c,var(--accent)); border-radius:8px; padding:12px 14px; }
.card .label { color:var(--muted); font-size:12px; }
.card .value { font-size:22px; font-weight:600; }
.card .sub { color:var(--muted); font-size:12px; }
.up { color:#c62828; } .down { color:#2e7d32; }
.panel { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:16px; margin-bottom:14px; overflow-x:auto; }
.charts { display:grid; grid-template-columns:repeat(auto-fill,minmax(360px,1fr)); gap:14px; }
.charts.wide { grid-template-columns:repeat(auto-fill,minmax(520px,1fr)); }
.chart { background:var(--card); border:1px solid var(--line); border-top:3px solid var(--c,var(--accent)); border-radius:8px; padding:12px 14px 8px; position:relative; }
.chart .title { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.chart .title b { font-size:14px; }
.chart .title span { color:var(--muted); font-size:12px; }
.chart .members { color:var(--muted); font-size:12px; margin-top:4px; }
.plot { width:100%; }
.plot svg { width:100%; height:auto; display:block; overflow:visible; }
.tip { position:absolute; pointer-events:none; background:#102a43; color:#fff; font-size:12px; padding:4px 8px; border-radius:4px; white-space:nowrap; display:none; z-index:2; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th, td { padding:6px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; position:sticky; left:0; background:inherit; }
tr { background:#fff; }
th { color:var(--muted); font-weight:600; background:#fafbfc; }
.scroll { max-height:460px; overflow:auto; }
.note { color:var(--muted); font-size:13px; }
.tools { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:6px 0 4px; }
.tools input { padding:7px 10px; border:1px solid var(--line); border-radius:6px; font:inherit; min-width:240px; }
.jump { display:flex; flex-wrap:wrap; gap:6px; }
.jump a { font-size:12px; padding:3px 9px; border-radius:12px; background:#fff; border:1px solid var(--line); color:var(--ink); text-decoration:none; }
details summary { cursor:pointer; color:var(--accent); margin:8px 0; }
.v { display:none; } body.v-history .v-history, body.v-no_history .v-no_history { display:block; }
footer { border-top:1px solid var(--line); background:#fff; padding:18px 32px; display:flex; align-items:center;
         justify-content:center; gap:14px; color:var(--muted); font-size:13px; }
footer img { height:44px; width:auto; }
footer b { color:var(--ink); }
@media print { nav, .bar, .tools { display:none; } .page { display:block !important; page-break-before:always; } }
"""

# Plain-JavaScript charts: a line chart per series and a ranking bar chart.
# No libraries, so the page works offline and stays small.
_JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
let V = D.versions[0].key;
const NS = 'http://www.w3.org/2000/svg';
const mnum = s => { const [y, m] = s.split('-').map(Number); return y * 12 + m - 1; };
const mstr = n => `${Math.floor(n / 12)}-${String(n % 12 + 1).padStart(2, '0')}`;
function nice(lo, hi, n) {
  const span = hi - lo || 1, raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(k => k * p).find(s => span / s <= n) || 10 * p;
  const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}
function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e); return e;
}
function line(box, pts, color, ref) {
  box.innerHTML = '';
  if (!pts || !pts.length) { box.innerHTML = '<p class="note">No values for this version.</p>'; return; }
  const W = 460, H = 210, L = 40, R = 10, T = 10, B = 26;
  const xs = pts.map(p => mnum(p[0])), ys = pts.map(p => p[1]);
  let lo = Math.min(...ys), hi = Math.max(...ys);
  if (ref != null) { lo = Math.min(lo, ref); hi = Math.max(hi, ref); }
  const pad = (hi - lo) * 0.08 || 5; lo -= pad; hi += pad;
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const X = v => L + (x1 === x0 ? (W - L - R) / 2 : (v - x0) / (x1 - x0) * (W - L - R));
  const Y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const svg = el('svg', {viewBox: `0 0 ${W} ${H}`, role: 'img'}, box);
  for (const t of nice(lo, hi, 4)) {
    el('line', {x1: L, x2: W - R, y1: Y(t), y2: Y(t), stroke: '#e4e7eb'}, svg);
    el('text', {x: L - 6, y: Y(t) + 4, 'text-anchor': 'end', 'font-size': 12, fill: '#616e7c'}, svg).textContent = t;
  }
  if (ref != null) el('line', {x1: L, x2: W - R, y1: Y(ref), y2: Y(ref), stroke: '#9aa5b1', 'stroke-dasharray': '3 3'}, svg);
  const span = x1 - x0 + 1, step = [1, 2, 3, 6, 12, 24, 36, 60, 120].find(s => span / s <= 4) || 120;
  for (let m = x0; m <= x1; m++) {
    if (step >= 12 ? (m % 12 === 0 && (Math.floor(m / 12) % (step / 12) === 0)) : (m % step === 0)) {
      el('line', {x1: X(m), x2: X(m), y1: H - B, y2: H - B + 4, stroke: '#9aa5b1'}, svg);
      el('text', {x: X(m), y: H - 6, 'text-anchor': 'middle', 'font-size': 12, fill: '#616e7c'}, svg).textContent = mstr(m);
    }
  }
  if (span <= 1) el('text', {x: X(x0), y: H - 6, 'text-anchor': 'middle', 'font-size': 11, fill: '#616e7c'}, svg).textContent = mstr(x0);
  let d = '', prev = null;
  pts.forEach((p, i) => { const m = xs[i]; d += (prev !== null && m === prev + 1 ? 'L' : 'M') + X(m).toFixed(1) + ' ' + Y(p[1]).toFixed(1); prev = m; });
  el('path', {d, fill: 'none', stroke: color, 'stroke-width': 1.8, 'stroke-linejoin': 'round'}, svg);
  if (pts.length <= 36) pts.forEach((p, i) => el('circle', {cx: X(xs[i]), cy: Y(p[1]), r: 2.4, fill: color}, svg));
  const last = pts[pts.length - 1];
  el('circle', {cx: X(xs[xs.length - 1]), cy: Y(last[1]), r: 3.5, fill: color, stroke: '#fff', 'stroke-width': 1.5}, svg);
  const guide = el('line', {y1: T, y2: H - B, stroke: '#9aa5b1', visibility: 'hidden'}, svg);
  const dot = el('circle', {r: 4, fill: color, stroke: '#fff', 'stroke-width': 1.5, visibility: 'hidden'}, svg);
  const tip = box.parentElement.querySelector('.tip');
  svg.addEventListener('mousemove', ev => {
    const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) / r.width * W;
    let best = 0; xs.forEach((m, i) => { if (Math.abs(X(m) - px) < Math.abs(X(xs[best]) - px)) best = i; });
    const gx = X(xs[best]), gy = Y(pts[best][1]);
    guide.setAttribute('x1', gx); guide.setAttribute('x2', gx); guide.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', gx); dot.setAttribute('cy', gy); dot.setAttribute('visibility', 'visible');
    if (tip) { tip.textContent = `${pts[best][0]}: ${pts[best][1].toFixed(1)}`; tip.style.display = 'block';
      const bx = box.getBoundingClientRect(), host = box.parentElement.getBoundingClientRect();
      tip.style.left = (bx.left - host.left + gx / W * bx.width + 8) + 'px'; tip.style.top = (bx.top - host.top + gy / H * bx.height - 28) + 'px'; }
  });
  svg.addEventListener('mouseleave', () => { guide.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); if (tip) tip.style.display = 'none'; });
}
function bars(box, rows, ref) {
  box.innerHTML = '';
  if (!rows.length) { box.innerHTML = '<p class="note">No values for this version.</p>'; return; }
  const W = 1000, row = 22, L = 190, R = 60, T = 6, H = T + rows.length * row + 22;
  const hi = Math.max(ref || 0, ...rows.map(r => r.value)) * 1.05, X = v => L + v / hi * (W - L - R);
  const svg = el('svg', {viewBox: `0 0 ${W} ${H}`, role: 'img'}, box);
  rows.forEach((r, i) => {
    const y = T + i * row;
    el('text', {x: L - 8, y: y + 15, 'text-anchor': 'end', 'font-size': 12, fill: '#1f2933'}, svg).textContent = r.name;
    el('rect', {x: L, y: y + 4, width: Math.max(1, X(r.value) - L), height: row - 8, rx: 3, fill: r.color}, svg);
    el('text', {x: X(r.value) + 6, y: y + 15, 'font-size': 12, fill: '#616e7c'}, svg).textContent = r.value.toFixed(1);
  });
  if (ref != null) {
    el('line', {x1: X(ref), x2: X(ref), y1: T, y2: H - 18, stroke: '#9aa5b1', 'stroke-dasharray': '3 3'}, svg);
    el('text', {x: X(ref), y: H - 4, 'text-anchor': 'middle', 'font-size': 11, fill: '#616e7c'}, svg).textContent = ref;
  }
}
function draw(page) {
  const v = D.data[V];
  page.querySelectorAll('[data-line]').forEach(box => {
    const [kind, name] = box.dataset.line.split('|');
    const series = (kind === 'g' ? v.groups : v.countries)[name];
    line(box, series, box.dataset.color, kind === 'a' ? null : 100);
    const lab = box.closest('.chart').querySelector('.title span');
    if (lab) lab.textContent = series && series.length ? `${series[series.length - 1][0]}: ${series[series.length - 1][1].toFixed(1)}` : 'no values';
  });
  page.querySelectorAll('[data-articles]').forEach(box => line(box, D.articles[box.dataset.articles], box.dataset.color, null));
  page.querySelectorAll('[data-rank]').forEach(box => {
    const src = box.dataset.rank === 'g' ? v.groups : v.countries, col = box.dataset.rank === 'g' ? D.groupColor : D.countryColor;
    const rows = Object.keys(src).filter(k => src[k].length).map(k => ({name: k, value: src[k][src[k].length - 1][1], color: col[k]}))
      .sort((a, b) => b.value - a.value);
    bars(box, rows, 100);
  });
}
function go(name) {
  if (!document.getElementById('p-' + name)) name = 'overview';
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('on', p.id === 'p-' + name));
  document.querySelectorAll('nav a').forEach(a => a.classList.toggle('on', a.dataset.p === name));
  draw(document.getElementById('p-' + name));
}
function version(key) {
  V = key; document.body.className = 'v-' + key;
  document.querySelectorAll('.switch button').forEach(b => b.classList.toggle('on', b.dataset.v === key));
  const lab = document.querySelector('.versionlabel'); if (lab) lab.textContent = D.versions.find(x => x.key === key).label;
  const page = document.querySelector('.page.on'); if (page) draw(page);
}
function filter(q) {
  q = q.trim().toLowerCase();
  document.querySelectorAll('#p-countries .chart').forEach(c => { c.style.display = !q || c.dataset.name.toLowerCase().includes(q) ? '' : 'none'; });
  document.querySelectorAll('#p-countries section').forEach(s => { s.style.display = [...s.querySelectorAll('.chart')].some(c => c.style.display !== 'none') ? '' : 'none'; });
}
window.addEventListener('hashchange', () => go(location.hash.slice(1)));
window.addEventListener('DOMContentLoaded', () => { version(V); go(location.hash.slice(1) || 'overview'); });
"""


def _logo_tag() -> str:
    """The CAPE logo as an inline image, if a logo.* file is in the package data folder."""
    import base64
    from pathlib import Path

    folder = Path(__file__).resolve().parent / "data"
    mime = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    for name in _LOGO_FILES:
        path = folder / name
        if path.exists():
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            return f'<img src="data:{mime[path.suffix.lower()]};base64,{data}" alt="{html.escape(CREDIT)} logo">'
    return ""


def _footer() -> str:
    return (f"<footer>{_logo_tag()}<span>Made with <b>CAPEnewsindex</b> {__version__} · "
            f"<b>{html.escape(CREDIT)}</b></span></footer>")


def _e(text) -> str:
    return html.escape(str(text))


def _table(df: pd.DataFrame, *, index: bool = False, floats: int = 1) -> str:
    if df is None or df.empty:
        return '<p class="note">No rows.</p>'
    if index:
        df = df.reset_index()
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_integer_dtype(df[col]):
            df[col] = df[col].map(lambda v: f"{v:,}")
    return df.to_html(index=False, border=0, float_format=lambda x: f"{x:,.{floats}f}", na_rep="")


def _series(table: pd.DataFrame | None, key: str, value: str) -> dict[str, list]:
    """{name: [[year_month, value], ...]} for the embedded data."""
    if table is None or table.empty:
        return {}
    out = {}
    for name, g in table.sort_values("year_month").groupby(key, sort=True):
        out[str(name)] = [[str(m), round(float(v), 3)] for m, v in zip(g["year_month"], g[value]) if pd.notna(v)]
    return out


def _sections(countries: list[str], blocks: dict[str, list[str]]) -> list[tuple[str, list[str]]]:
    """Countries organised under headings: the smallest group each belongs to, else its African region."""
    from .aggregate import AFRICA_REGIONS

    everyone = set(countries)
    # A block holding every country of the run (e.g. "Africa") is not a useful heading.
    blocks = {k: v for k, v in blocks.items() if not everyone <= set(v) or len(everyone) == 1}

    def home(country, candidates):
        found = [(len(m), name) for name, m in candidates.items() if country in m]
        return min(found)[1] if found else None

    order: dict[str, list[str]] = {}
    for c in countries:
        name = home(c, blocks) or home(c, AFRICA_REGIONS)
        order.setdefault(name or "", []).append(c)
    if list(order) == [""]:
        return [("", countries)]
    named = [(k, v) for k, v in order.items() if k]
    named.sort(key=lambda kv: kv[0])
    if "" in order:
        named.append(("Other countries", order[""]))
    return named


def _last_months(table: pd.DataFrame | None, key: str, value: str, months: int) -> pd.DataFrame:
    """Rows = countries (or groups), columns = the last ``months`` months."""
    if table is None or table.empty:
        return pd.DataFrame()
    wide = table.pivot(index=key, columns="year_month", values=value)
    wide = wide[sorted(wide.columns)[-months:]].round(1)
    wide.columns.name = None
    wide.index.name = key
    return wide


def _cards(latest: list[tuple[str, str, float, float | None, str]]) -> str:
    out = []
    for name, month, value, change, color in latest:
        sub = ""
        if change is not None:
            cls = "up" if change > 0 else "down"
            sub = f'<span class="{cls}">{"▲" if change > 0 else "▼"} {abs(change):.1f}</span> vs previous month'
        out.append(f'<div class="card" style="--c:{color}"><div class="label">{_e(name)} · {_e(month)}</div>'
                   f'<div class="value">{value:.1f}</div><div class="sub">{sub}</div></div>')
    return f'<div class="cards">{"".join(out)}</div>'


def _latest(series: dict[str, list], colors: dict[str, str]):
    rows = []
    for name, pts in series.items():
        if pts:
            change = pts[-1][1] - pts[-2][1] if len(pts) > 1 else None
            rows.append((name, pts[-1][0], pts[-1][1], change, colors.get(name, _OTHER)))
    return rows


def _chart(kind: str, name: str, color: str, latest: str = "", members: str = "") -> str:
    return (f'<div class="chart" style="--c:{color}" data-name="{_e(name)}" id="{kind}-{_e(name)}">'
            f'<div class="title"><b>{_e(name)}</b><span>{latest}</span></div>'
            f'<div class="plot" data-line="{kind}|{_e(name)}" data-color="{color}"></div><div class="tip"></div>'
            + (f'<div class="members">{members}</div>' if members else "") + "</div>")


def _coverage(result, start: str, end: str, sections, colors) -> tuple[str, dict]:
    m = result.measure
    hits = f"{m.lower()}_articles"
    c = result.counts
    c = c[(c["year_month"] >= start) & (c["year_month"] <= end)]
    if c.empty:
        return '<p class="note">No articles in this period.</p>', {}
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
    monthly = c.groupby(["country", "year_month"])["all_articles"].sum().reset_index()
    articles = _series(monthly, "country", "all_articles")
    charts = []
    for heading, members in sections:
        boxes = "".join(
            f'<div class="chart" style="--c:{colors.get(n, _OTHER)}"><div class="title"><b>{_e(n)}</b>'
            f'<span>articles per month</span></div><div class="plot" data-articles="{_e(n)}" '
            f'data-color="{colors.get(n, _OTHER)}"></div><div class="tip"></div></div>'
            for n in members if n in articles
        )
        if boxes:
            charts.append((f"<h3>{_e(heading)}</h3>" if heading else "") + f'<div class="charts">{boxes}</div>')
    html_out = (
        "<h2>Articles per country</h2><div class=\"panel scroll\">" + _table(per_country) + "</div>"
        + "<h2>Newspapers</h2><div class=\"panel scroll\">" + _table(per_site) + "</div>"
        + "<h2>Articles per month (after removing duplicates)</h2>" + "".join(charts)
    )
    return html_out, articles


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
    return ("<h2>Keywords used: number of terms per group</h2><div class=\"panel scroll\">" + _table(counts) + "</div>"
            + f"<h2>Every term used ({len(kw):,})</h2><div class=\"panel scroll\">{full}</div>")


def build(result, months: int = 12, version: str = "both") -> str:
    """The dashboard as one HTML string."""
    s = result.settings
    m = result.measure
    start, end = s["period"].split("..")
    versions = result._versions(version)
    today = datetime.date.today().isoformat()

    # --- data for the charts --------------------------------------------------
    data = {key: {"countries": _series(table, "country", m), "groups": _series(groups, "group", "index")}
            for key, _label, table, groups in versions}
    countries = sorted({c for d in data.values() for c in d["countries"]} | set(s.get("countries", [])))
    group_names = sorted({g for d in data.values() for g in d["groups"]})
    blocks = {k: list(v) for k, v in (s.get("groups") or {}).items()}
    sections = _sections(countries, blocks)
    section_color = {name: _PALETTE[i % len(_PALETTE)] for i, (name, _members) in enumerate(sections) if name}
    country_color = {c: section_color.get(name, _OTHER) for name, members in sections for c in members}
    spare = iter(c for c in _PALETTE[::-1] if c not in section_color.values())
    group_color = {}
    for g in group_names:
        if g in section_color:
            group_color[g] = section_color[g]
        elif len(blocks.get(g, [])) and all(len(blocks.get(g, [])) >= len(m) for m in blocks.values()):
            group_color[g] = "#102a43"  # the block holding every country, e.g. Africa
        else:
            group_color[g] = next(spare, _OTHER)
    coverage_html, articles = _coverage(result, start, end, sections, country_color)
    payload = {
        "versions": [{"key": key, "label": label} for key, label, _t, _g in versions],
        "data": data, "articles": articles, "countryColor": country_color, "groupColor": group_color,
    }

    def per_version(render) -> str:
        return "".join(f'<div class="v v-{key}">{render(key, label, table, groups)}</div>'
                       for key, label, table, groups in versions)

    # --- Overview ----------------------------------------------------------------
    def overview(key, label, table, groups):
        d = data[key]
        parts = []
        if d["groups"]:
            parts += ["<h2>Groups of countries · latest</h2>", _cards(_latest(d["groups"], group_color))]
        parts.append("<h2>Countries · latest</h2>")
        for name, members in sections:
            rows = _latest({c: d["countries"][c] for c in members if c in d["countries"]}, country_color)
            if rows:
                parts.append((f'<h3><span class="dot" style="background:{section_color.get(name, _OTHER)}"></span>'
                              f"{_e(name)}</h3>" if name else "") + _cards(rows))
        if not d["countries"]:
            parts.append('<p class="note">No index values in this version.</p>')
        return "".join(parts)

    rank = ""
    if group_names:
        rank += ('<h2>Groups ranked by the latest month</h2><div class="panel"><div class="plot" data-rank="g"></div></div>')
    rank += ('<h2>Countries ranked by the latest month</h2><div class="panel"><div class="plot" data-rank="c"></div></div>')
    summary = per_version(lambda key, label, t, g: "<h2>Summary per country</h2><div class=\"panel scroll\">"
                          + _table(result.table(key.replace("_", " "))) + "</div>")
    p_overview = per_version(overview) + rank + summary

    # --- Regions -------------------------------------------------------------------
    p_regions = ""
    if group_names:
        def regions(key, label, table, groups):
            if groups is None or groups.empty:
                return ('<p class="note">No group series in this version: each country needs 2+ months with a '
                        "changing index in the scaling period.</p>")
            return (f"<h2>Last {months} months</h2><div class=\"panel scroll\">"
                    + _table(_last_months(groups, "group", "index", months), index=True) + "</div>")
        cards = []
        for g in group_names:
            members = blocks.get(g, [])
            n = f"{len(members)} countries: " + ", ".join(members) if members else ""
            cards.append(_chart("g", g, group_color[g], "", _e(n)))
        p_regions = (
            "<p class=\"note\">Each group is the weighted average of its countries' standardised index, "
            "shown as 100 + 10 × standard deviations (GDP weights unless you chose otherwise).</p>"
            f'<div class="charts wide">{"".join(cards)}</div>' + per_version(regions)
        )

    # --- Countries -----------------------------------------------------------------
    jump = "".join(f'<a href="#countries" onclick="document.getElementById(\'s-{i}\').scrollIntoView();return false">'
                   f"{_e(name)}</a>" for i, (name, _members) in enumerate(sections) if name)
    blocks_html = []
    for i, (name, members) in enumerate(sections):
        charts = "".join(_chart("c", c, country_color[c]) for c in members)
        head = (f'<h3><span class="dot" style="background:{section_color.get(name, _OTHER)}"></span>{_e(name)} '
                f'<span class="note">({len(members)})</span></h3>') if name else ""
        blocks_html.append(f'<section id="s-{i}">{head}<div class="charts">{charts}</div></section>')
    country_tables = per_version(lambda key, label, t, g: f"<h2>Last {months} months</h2><div class=\"panel scroll\">"
                                 + _table(_last_months(t, "country", m, months), index=True) + "</div>"
                                 + f"<details><summary>All months ({0 if t is None else len(t):,} rows)</summary>"
                                 + "<div class=\"panel scroll\">" + _table(t, floats=3) + "</div></details>")
    p_countries = (
        '<div class="tools"><input type="search" placeholder="Find a country..." oninput="filter(this.value)">'
        f'<div class="jump">{jump}</div></div>' + "".join(blocks_html) + country_tables
    )

    # --- About -----------------------------------------------------------------------
    groups_used = ", ".join(s.get("keyword_groups", ["economic", "policy", "uncertainty"]))
    about = (
        "<h2>How to read this</h2><div class=\"panel\">"
        "<p><b>With history</b>: each newspaper's scaling and the country mean are fixed on the history "
        "period, so 100 = the history average and past values never change when new months are added.</p>"
        "<p><b>No history</b>: scaled on the months shown, so 100 = their average; values shift when the "
        "period changes.</p>"
        f"<p><b>Method</b>: Baker, Bloom and Davis (2016). An article counts for the {_e(m)} index when it "
        f"contains at least one term from each keyword group ({_e(groups_used)}). For each newspaper, the "
        "share of such articles is divided by its standard deviation over the scaling period; the country "
        "value is the average across newspapers, rescaled so the scaling period averages 100.</p>"
        "<p><b>Groups of countries</b>: each country's index is standardised over the scaling period; a group "
        "is the weighted average of its countries, shown as 100 + 10 × standard deviations.</p></div>"
        f"<h2>Settings</h2><div class=\"panel\"><table>"
        + "".join(f"<tr><td>{_e(k)}</td><td style='text-align:left;white-space:normal'>{_e(v)}</td></tr>"
                  for k, v in (("index", s.get("title", m)), ("period", s["period"]), ("mode", s["mode"]),
                               ("countries", f"{len(s['countries'])}: " + ", ".join(s["countries"])),
                               ("archive", s.get("archive", "")), ("made", f"{today}, CAPEnewsindex {__version__}")))
        + "</table></div>"
    )
    if len(result.skipped_files):
        about += ("<h2>Files that could not be read</h2><div class=\"panel scroll\">"
                  + _table(result.skipped_files) + "</div>")

    pages = [("overview", "Overview", p_overview)]
    if p_regions:
        pages.append(("regions", "Regions" if any(g in section_color for g in group_names) else "Groups", p_regions))
    pages += [("countries", "Countries", p_countries), ("newspapers", "Newspapers", coverage_html),
              ("keywords", "Keywords", _keywords(result)), ("about", "About", about)]
    nav = "".join(f'<a href="#{k}" data-p="{k}">{_e(t)}</a>' for k, t, _h in pages)
    body = "".join(f'<div class="page" id="p-{k}">{h}</div>' for k, _t, h in pages)
    switch = ""
    if len(versions) > 1:
        switch = '<div class="switch">' + "".join(
            f'<button data-v="{key}" onclick="version(\'{key}\')">{"With history" if key == "history" else "No history"}</button>'
            for key, _label, _t, _g in versions) + "</div>"
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    n = len(s["countries"])
    subtitle = (f"{n} countr{'y' if n == 1 else 'ies'} · {_e(s['period'])} · {_e(s['mode'])}"
                + (f" · {len(group_names)} groups" if group_names else ""))

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(m)} dashboard {_e(s['period'])}</title><style>{_CSS}</style></head>
<body class="v-{versions[0][0]}">
<header><h1>{_e(s.get('title', 'Economic Policy Uncertainty'))} dashboard</h1>
<p>{subtitle} · made {today}</p><nav>{nav}</nav></header>
<div class="bar">{switch}<span class="versionlabel"></span></div>
<main>{body}</main>
{_footer()}
<script type="application/json" id="data">{blob}</script>
<script>{_JS}</script>
</body></html>"""


def write(result, path, months: int = 12, version: str = "both"):
    from pathlib import Path

    path = Path(path)
    path.write_text(build(result, months=months, version=version), encoding="utf-8")
    return path
