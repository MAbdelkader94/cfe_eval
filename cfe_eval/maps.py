"""
maps.py - maps of the gages on the aridity zones, in an equal-area projection.

Projection: Albers Equal Area Conic for the conterminous United States
(EPSG:5070: standard parallels 29.5 and 45.5 N, origin 23 N, 96 W, GRS80).
Areas keep their true proportions, so the size of a climate zone on the map
is its real size. The base map (static/basemap_albers.json: aridity zones and
state borders, already projected) and the projection below need only numpy
and matplotlib; no GIS library is required to draw the maps.
"""
from __future__ import annotations

import json
from functools import lru_cache

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as MplPath

from . import config as cfg

# light fills so the gage symbols stay readable on top
ZONE_FILL = {"Arid": "#f3d9b1", "Semi-arid": "#f7ecc4", "Semi-humid": "#dcecc8", "Humid": "#cfe3f1"}

# EPSG:5070 parameters
_A, _F = 6378137.0, 1 / 298.257222101
_LAT1, _LAT2, _LAT0, _LON0 = np.radians([29.5, 45.5, 23.0, -96.0])


def albers(lon, lat):
    """Longitude, latitude in degrees -> x, y in metres (EPSG:5070).
    Ellipsoidal Albers Equal Area Conic, Snyder (1987), USGS Professional Paper 1395, eq. 14-1 to 14-12."""
    e2 = _F * (2 - _F)
    e = np.sqrt(e2)

    def q(phi):
        s = np.sin(phi)
        return (1 - e2) * (s / (1 - e2 * s * s) - np.log((1 - e * s) / (1 + e * s)) / (2 * e))

    def m(phi):
        return np.cos(phi) / np.sqrt(1 - e2 * np.sin(phi) ** 2)

    n = (m(_LAT1) ** 2 - m(_LAT2) ** 2) / (q(_LAT2) - q(_LAT1))
    c = m(_LAT1) ** 2 + n * q(_LAT1)
    rho0 = _A * np.sqrt(c - n * q(_LAT0)) / n
    lam, phi = np.radians(np.asarray(lon, float)), np.radians(np.asarray(lat, float))
    rho = _A * np.sqrt(c - n * q(phi)) / n
    theta = n * (lam - _LON0)
    return rho * np.sin(theta), rho0 - rho * np.cos(theta)


@lru_cache(maxsize=1)
def load_basemap() -> dict:
    return json.loads((cfg.REPO / "static" / "basemap_albers.json").read_text())


def _zone_patch(polygons, **kw):
    verts, codes = [], []
    for poly in polygons:
        for ring in poly:
            verts += ring
            codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(ring) - 2) + [MplPath.CLOSEPOLY]
    return PathPatch(MplPath(verts, codes), **kw)


def draw_basemap(ax, zones: bool = True, states: bool = True):
    """Aridity zones (light fills) and state borders on ax, axes hidden."""
    base = load_basemap()
    if zones:
        for name in cfg.ZONES:
            ax.add_patch(_zone_patch(base["zones"][name], facecolor=ZONE_FILL[name], edgecolor="none", zorder=1))
    if states:
        ax.add_collection(LineCollection(base["states"], colors="0.45", linewidths=0.6, zorder=2))
    ax.set_aspect("equal")
    ax.set_xlim(-2.42e6, 2.32e6)
    ax.set_ylim(0.22e6, 3.22e6)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    return ax


def zone_handles():
    return [Patch(facecolor=ZONE_FILL[z], edgecolor="0.45", linewidth=0.6, label=z) for z in cfg.ZONES]


def class_labels(bounds, fmt="{:g}", unit=""):
    """Legend text for classes: below b0, b0 to b1, ..., above bn."""
    lab = [f"below {fmt.format(bounds[0])}{unit}"]
    lab += [f"{fmt.format(a)} to {fmt.format(b)}{unit}" for a, b in zip(bounds[:-1], bounds[1:])]
    return lab + [f"above {fmt.format(bounds[-1])}{unit}"]


def metric_map(ax, gages, values, bounds, colors, size=34):
    """Gages as circles coloured by class of values. bounds: n inner class limits,
    colors: n + 1 colours. gages needs the columns lon and lat (same order as values).
    Gages without a value are not drawn."""
    draw_basemap(ax)
    v = np.asarray(values, float)
    ok = np.isfinite(v)
    x, y = albers(gages["lon"].to_numpy()[ok], gages["lat"].to_numpy()[ok])
    cls = np.digitize(v[ok], bounds)
    order = np.argsort(np.abs(cls - (len(colors) - 1) / 2))        # extreme classes drawn last, on top
    ax.scatter(x[order], y[order], s=size, c=np.asarray(colors, dtype=object)[cls[order]].tolist(),
               edgecolors="black", linewidths=0.35, zorder=3)
    return ax


def figure_metric_maps(df, value, title, bounds, colors, labels=None, products=None, figsize=(20, 5.9)):
    """One map per product, side by side. df: one row per gage and product with
    the columns gage, product, lon, lat and value. Two legends below the maps:
    the classes of the metric and the aridity zones."""
    products = products or list(cfg.PRODUCTS)
    labels = labels or class_labels(bounds)
    fig, axes = plt.subplots(1, len(products), figsize=figsize)
    for ax, prod in zip(np.atleast_1d(axes), products):
        d = df[df["product"] == prod]
        metric_map(ax, d, d[value], bounds, colors)
        ax.set_title(cfg.PRODUCT_LABEL.get(prod, prod))
    fig.tight_layout(w_pad=0.2, rect=(0, 0.2, 1, 1))
    h = [Line2D([], [], marker="o", linestyle="", markersize=11, markerfacecolor=c, markeredgecolor="black",
                markeredgewidth=0.5, label=lab) for c, lab in zip(colors, labels)]
    fig.legend(handles=h, title=title, loc="lower center", bbox_to_anchor=(0.5, 0.085), ncol=len(h),
               frameon=False, columnspacing=1.2, handletextpad=0.2, title_fontproperties={"weight": "bold"})
    fig.legend(handles=zone_handles(), loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=4, frameon=False,
               columnspacing=1.6)
    cols = [c for c in ["gage", "product", "aridity_zone", "lat", "lon", value] if c in df.columns]
    fig.cfe_data = df.loc[df["product"].isin(products), cols].dropna().sort_values(["product", "gage"]).reset_index(drop=True)
    return fig


def colors_from(cmap: str, n: int, lo: float = 0.0, hi: float = 1.0) -> list[str]:
    """n colours taken evenly from a matplotlib colour map (between lo and hi of its range)."""
    from matplotlib.colors import to_hex
    cm_ = plt.get_cmap(cmap)
    return [to_hex(cm_(v)) for v in np.linspace(lo, hi, n)]


def figure_category_map(gages, category, colors: dict, title=None, figsize=(13.33, 7.2), size=46):
    """One map, gages coloured by a category column (for example keep or drop).
    colors: {category value: colour}; values are drawn in that order."""
    fig, ax = plt.subplots(figsize=figsize)
    draw_basemap(ax)
    for val, c in colors.items():
        d = gages[category == val]
        x, y = albers(d["lon"].to_numpy(), d["lat"].to_numpy())
        ax.scatter(x, y, s=size, color=c, edgecolors="black", linewidths=0.4, zorder=3, label=f"{val} ({len(d)})")
    if title:
        ax.set_title(title)
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    h, lab = ax.get_legend_handles_labels()
    fig.legend(h, lab, loc="lower center", bbox_to_anchor=(0.5, 0.045), ncol=len(h), frameon=False)
    fig.legend(handles=zone_handles(), loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=4, frameon=False)
    return fig
