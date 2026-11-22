"""
00_build_basemap.py - build static/basemap_albers.json, the small base map used
by cfe_eval/maps.py: the four aridity zones and the state borders of the
conterminous United States, already projected to Albers Equal Area (EPSG:5070)
and simplified. Run once on a machine with geopandas; the result is committed.

    python scripts/00_build_basemap.py --zones Aridity_zones/AZ.shp --states ne_50m_admin_1_states_provinces.geojson

Inputs  AZ.shp      aridity zones (from Aridity_zones.rar)
        states      Natural Earth 1:50m admin-1 states and provinces (public domain),
                    https://github.com/nvkelso/natural-earth-vector (geojson folder)
"""
import argparse
import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon

LABEL = {"arid": "Arid", "semiarid": "Semi-arid", "subhumid": "Semi-humid", "humid": "Humid"}


def rings(geom, min_area_m2):
    """[[exterior, hole, ...], ...] with coordinates rounded to 100 m."""
    polys = [geom] if isinstance(geom, Polygon) else [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    out = []
    for p in polys:
        if p.area < min_area_m2:
            continue
        rr = [[[round(x, -2), round(y, -2)] for x, y in p.exterior.coords]]
        rr += [[[round(x, -2), round(y, -2)] for x, y in h.coords] for h in p.interiors
               if Polygon(h).area >= min_area_m2]
        out.append(rr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zones", required=True)
    ap.add_argument("--states", required=True)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "static" / "basemap_albers.json"))
    a = ap.parse_args()

    st = gpd.read_file(a.states)
    st = st[(st["iso_a2"] == "US") & ~st["postal"].isin(["AK", "HI"])].to_crs("EPSG:5070")
    conus = st.geometry.union_all().buffer(0)
    z = gpd.read_file(a.zones).to_crs("EPSG:5070")
    z["geometry"] = z.geometry.make_valid().intersection(conus)

    base = {"crs": "EPSG:5070", "zones": {}, "states": []}
    for _, r in z.iterrows():
        g = r.geometry.simplify(3000, preserve_topology=True)
        base["zones"][LABEL[r["name"]]] = rings(g, 2.5e8)          # drop slivers below 250 km2
    for g in st.geometry:
        g = g.simplify(2000, preserve_topology=True)
        for p in (g.geoms if isinstance(g, MultiPolygon) else [g]):
            if p.area >= 1e8:
                base["states"].append([[round(x, -2), round(y, -2)] for x, y in p.exterior.coords])
    Path(a.out).write_text(json.dumps(base, separators=(",", ":")))
    print("written", a.out, Path(a.out).stat().st_size // 1024, "KB",
          {k: len(v) for k, v in base["zones"].items()}, len(base["states"]), "state rings")


if __name__ == "__main__":
    main()
