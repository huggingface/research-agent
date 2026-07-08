# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "matplotlib>=3.8,<4",
# ]
# ///
"""Matplotlib helpers for Birch-styled inline SVG charts.

The helpers are deliberately small: they make Matplotlib output feel native in
Birch HTML artifacts without hiding the underlying Matplotlib API.
"""

from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
import re
from typing import Iterator

import matplotlib as mpl
import matplotlib.pyplot as plt


COLORS = {
    "ivory": "#FAF9F5",
    "surface": "#FFFFFF",
    "slate": "#141413",
    "clay": "#D97757",
    "clay_dark": "#B85C3E",
    "oat": "#E3DACC",
    "olive": "#788C5D",
    "rust": "#B04A3F",
    "sky": "#6A8CAF",
    "gray_100": "#F0EEE6",
    "gray_200": "#DED9CD",
    "gray_300": "#D1CFC5",
    "gray_500": "#87867F",
    "gray_700": "#3D3D3A",
}

PALETTE = [
    COLORS["clay"],
    COLORS["olive"],
    COLORS["sky"],
    COLORS["rust"],
    COLORS["clay_dark"],
    COLORS["gray_700"],
]


def rc_params(*, transparent: bool = True) -> dict[str, object]:
    """Return rcParams for charts embedded in Birch HTML."""
    face = "none" if transparent else COLORS["ivory"]
    return {
        "figure.facecolor": face,
        "axes.facecolor": face,
        "savefig.facecolor": face,
        "savefig.edgecolor": face,
        "savefig.transparent": transparent,
        "font.family": "DejaVu Sans",
        "font.size": 10.5,
        "text.color": COLORS["slate"],
        "axes.labelcolor": COLORS["gray_700"],
        "axes.edgecolor": COLORS["gray_300"],
        "axes.linewidth": 1.0,
        "axes.titlecolor": COLORS["slate"],
        "axes.titlesize": 13,
        "axes.titleweight": "normal",
        "axes.labelsize": 10,
        "axes.prop_cycle": mpl.cycler(color=PALETTE),
        "xtick.color": COLORS["gray_500"],
        "ytick.color": COLORS["gray_500"],
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "grid.color": COLORS["gray_200"],
        "grid.linewidth": 0.8,
        "grid.alpha": 1.0,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "legend.handlelength": 1.4,
        "legend.handletextpad": 0.45,
        "svg.fonttype": "none",
        "figure.constrained_layout.use": True,
    }


@contextmanager
def birch_theme(*, transparent: bool = True) -> Iterator[None]:
    """Temporarily apply the Birch Matplotlib theme."""
    with mpl.rc_context(rc_params(transparent=transparent)):
        yield


def polish_axes(ax: mpl.axes.Axes, *, grid_axis: str = "y") -> None:
    """Apply Birch axis cleanup to an existing axes."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(COLORS["gray_300"])
    ax.spines["bottom"].set_color(COLORS["gray_300"])
    ax.tick_params(axis="both", length=0, pad=7)
    ax.grid(axis=grid_axis, zorder=0)
    ax.set_axisbelow(True)


def svg_string(fig: mpl.figure.Figure) -> str:
    """Serialize a Matplotlib figure as inlineable SVG."""
    buffer = StringIO()
    fig.savefig(buffer, format="svg", bbox_inches="tight", pad_inches=0.04, metadata={"Date": None})
    svg = buffer.getvalue()
    start = svg.find("<svg")
    svg = svg[start:] if start >= 0 else svg
    svg = re.sub(r"<metadata>.*?</metadata>\s*", "", svg, flags=re.DOTALL)
    return svg


def close(fig: mpl.figure.Figure) -> None:
    """Close a figure after SVG export."""
    plt.close(fig)
