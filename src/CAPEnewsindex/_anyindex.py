"""Let the summary, chart and report helpers work for any index name (EPU, TPU, PU, ...).

The helpers are written for a value column called ``EPU``. :func:`any_index`
wraps one so it finds your index column (``TPU``, ``EgPU``, ...), works on it,
and gives the result back under your name: tables keep your column names, and
text and chart labels say "TPU" instead of "EPU".
"""

from __future__ import annotations

import functools
import re

import pandas as pd

from .index import value_column

_WORD = re.compile(r"\bEPU\b")


def label(table: pd.DataFrame) -> str:
    """The index name to show for ``table``: its value column (EPU, TPU, ...)."""
    try:
        return value_column(table)
    except ValueError:
        return "EPU"


def _relabel_text(text: str, name: str) -> str:
    return _WORD.sub(name, text) if isinstance(text, str) else text


def _relabel_figure(fig, name: str):
    axes = getattr(fig, "axes", None)
    if isinstance(axes, list):  # matplotlib
        for ax in axes:
            ax.set_ylabel(_relabel_text(ax.get_ylabel(), name))
            ax.set_xlabel(_relabel_text(ax.get_xlabel(), name))
            ax.set_title(_relabel_text(ax.get_title(), name))
            legend = ax.get_legend()
            if legend is not None:
                for t in legend.get_texts():
                    t.set_text(_relabel_text(t.get_text(), name))
            ticks = [t.get_text() for t in ax.get_xticklabels()]
            if any(_WORD.search(t) for t in ticks):
                ax.set_xticks(ax.get_xticks())
                ax.set_xticklabels([_relabel_text(t, name) for t in ticks])
        if getattr(fig, "_suptitle", None) is not None:
            fig._suptitle.set_text(_relabel_text(fig._suptitle.get_text(), name))
        return fig
    layout = getattr(fig, "layout", None)
    if layout is not None:  # plotly
        try:
            if layout.title and layout.title.text:
                layout.title.text = _relabel_text(layout.title.text, name)
            for key in ("yaxis", "xaxis", "yaxis2"):
                axis = getattr(layout, key, None)
                if axis is not None and axis.title and axis.title.text:
                    axis.title.text = _relabel_text(axis.title.text, name)
            for trace in fig.data:
                if getattr(trace, "name", None):
                    trace.name = _relabel_text(trace.name, name)
        except Exception:  # labels are cosmetic; never fail a chart over them
            pass
    return fig


def _back(out, name: str):
    if isinstance(out, pd.DataFrame):
        return out.rename(columns={"EPU": name, "EPU_smoothed": f"{name}_smoothed"})
    if isinstance(out, str):
        return _relabel_text(out, name)
    if isinstance(out, tuple):
        return tuple(_back(o, name) for o in out)
    if out is not None and (hasattr(out, "axes") or hasattr(out, "layout")):
        return _relabel_figure(out, name)
    return out


def any_index(fn):
    """Decorator: run ``fn`` (written for an ``EPU`` column) on any index column."""

    @functools.wraps(fn)
    def wrapper(result, *args, **kwargs):
        if not isinstance(result, pd.DataFrame) or "EPU" in result.columns or "country" not in result.columns:
            return fn(result, *args, **kwargs)
        name = value_column(result)
        renamed = result.rename(columns={name: "EPU", f"{name}_smoothed": "EPU_smoothed"})
        args = tuple("EPU" if isinstance(a, str) and a == name else a for a in args)
        kwargs = {k: ("EPU" if isinstance(v, str) and v == name else v) for k, v in kwargs.items()}
        return _back(fn(renamed, *args, **kwargs), name)

    return wrapper
