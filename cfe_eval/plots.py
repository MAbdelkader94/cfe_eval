"""
plots.py - the seasonal box plots by climate type used in the notebooks.

One box = the distribution over gages of one metric, for one climate type
(aridity zone) and one season. Boxes show the quartiles and the median. The
dashed whiskers reach the most extreme value within 1.5 box heights of the box
(whis=1.5, the usual rule); pass whis=(5, 95) for percentile whiskers. Points
beyond the whiskers are not drawn.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

from . import config as cfg

# season -> (edge colour, fill colour)
SEASON_COLORS = {"Fall": ("#d98a5f", "#f2b89b"), "Winter": ("#1a1ab8", "#9a9af5"),
                 "Spring": ("#12c41a", "#98f59c"), "Summer": ("#d1305a", "#f7aabb")}


def slide_style(base: float = 16.0) -> None:
    """Fonts large enough for a projected slide; all text black."""
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": base, "axes.titlesize": base + 2,
        "axes.labelsize": base + 2, "axes.labelweight": "bold", "axes.titleweight": "bold",
        "xtick.labelsize": base, "ytick.labelsize": base, "legend.fontsize": base,
        "text.color": "black", "axes.labelcolor": "black", "axes.edgecolor": "black",
        "xtick.color": "black", "ytick.color": "black", "figure.dpi": 100, "savefig.dpi": 300,
        "savefig.bbox": "tight", "axes.spines.top": True, "axes.spines.right": True})


def season_zone_boxes(ax, df: pd.DataFrame, value: str, whis=1.5, ref: float | None = None,
                      zone_counts: bool = True, min_gages: int = 5):
    """Grouped box plot on ax: climate types on the x axis, one box per season.

    df needs the columns aridity_zone, season, gage and value (one row per gage
    and season). A box is drawn only when at least min_gages gages have a value.
    """
    zones, seasons = cfg.ZONES, cfg.SEASONS
    width, gap = 0.8, 0.1
    step = width + gap
    span = len(seasons) * step
    for zi, zone in enumerate(zones):
        for si, season in enumerate(seasons):
            v = df.loc[(df["aridity_zone"] == zone) & (df["season"] == season), value].dropna().to_numpy()
            if len(v) < min_gages:
                continue
            edge, face = SEASON_COLORS[season]
            x = zi * (span + 1.0) + si * step
            ax.boxplot([v], positions=[x], widths=width, whis=whis, showfliers=False, patch_artist=True,
                       boxprops=dict(facecolor=face, edgecolor=edge, linewidth=1.8),
                       medianprops=dict(color=edge, linewidth=2.0),
                       whiskerprops=dict(color=edge, linewidth=1.6, linestyle=(0, (4, 3))),
                       capprops=dict(color=edge, linewidth=1.8), manage_ticks=False)
    centers = [zi * (span + 1.0) + (span - step) / 2 for zi in range(len(zones))]
    for zi in range(1, len(zones)):
        ax.axvline(zi * (span + 1.0) - (1.0 + gap) / 2 - width / 2 + gap / 2, color="0.35", lw=1.0)
    if ref is not None:
        ax.axhline(ref, color="black", lw=1.0, zorder=0)
    labels = []
    for zone in zones:
        n = df.loc[df["aridity_zone"] == zone, "gage"].nunique()
        labels.append(f"{zone}\n({n} gages)" if zone_counts else zone)
    ax.set_xticks(centers)
    ax.set_xticklabels(labels, fontweight="bold")
    ax.set_xlim(-width / 2 - 0.45, (len(zones) - 1) * (span + 1.0) + span - step + width / 2 + 0.45)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color="0.88", lw=0.8)
    ax.set_axisbelow(True)
    for lab in ax.get_yticklabels():
        lab.set_fontweight("bold")
    return ax


def season_handles():
    return [Patch(facecolor=SEASON_COLORS[s][1], edgecolor=SEASON_COLORS[s][0], linewidth=1.8, label=s)
            for s in cfg.SEASONS]


def season_legend(ax, **kw):
    """Season legend inside one axes."""
    return ax.legend(handles=season_handles(), frameon=True, fancybox=False, edgecolor="black",
                     framealpha=1.0, **kw)


def season_legend_top(fig, top: float = 0.92):
    """Season legend in one row above the panels, clear of the data."""
    fig.tight_layout(w_pad=0.6, rect=(0, 0, 1, top))
    return fig.legend(handles=season_handles(), loc="upper center", ncol=len(cfg.SEASONS), frameon=True,
                      fancybox=False, edgecolor="black", bbox_to_anchor=(0.5, 1.0))


def figure_by_product(df: pd.DataFrame, value: str, ylabel: str, products=None, ref: float | None = None,
                      ylim=None, whis=1.5, figsize=(20, 8)):
    """One panel per product, side by side, sized for a 16:9 slide. The season
    legend sits above the panels.

    df: one row per gage, product and season with the columns gage, product,
    season, aridity_zone and value. Returns the figure.
    """
    products = products or list(cfg.PRODUCTS)
    fig, axes = plt.subplots(1, len(products), figsize=figsize, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, prod in zip(axes, products):
        season_zone_boxes(ax, df[df["product"] == prod], value, whis=whis, ref=ref, zone_counts=False)
        ax.set_title(cfg.PRODUCT_LABEL.get(prod, prod))
        ax.tick_params(axis="x", labelsize=plt.rcParams["xtick.labelsize"] - 2)
        if ylim:
            ax.set_ylim(*ylim)
    axes[0].set_ylabel(ylabel)
    fig.supxlabel("Climate type", fontweight="bold", fontsize=plt.rcParams["axes.labelsize"])
    season_legend_top(fig)
    return fig


def figure_single(df: pd.DataFrame, value: str, ylabel: str, product: str, ref: float | None = None,
                  ylim=None, whis=1.5, figsize=(13.33, 7.0), legend_loc="upper right"):
    """One product on a full slide, in the layout of the reference figures."""
    fig, ax = plt.subplots(figsize=figsize)
    season_zone_boxes(ax, df[df["product"] == product], value, whis=whis, ref=ref)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Climate type", labelpad=12)
    ax.set_title(cfg.PRODUCT_LABEL.get(product, product))
    if ylim:
        ax.set_ylim(*ylim)
    season_legend(ax, loc=legend_loc)
    fig.tight_layout()
    return fig
