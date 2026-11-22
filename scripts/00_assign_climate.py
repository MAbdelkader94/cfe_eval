"""
00_assign_climate.py - give every gage an aridity (climate) zone.

Run once on a machine with geopandas. The result, static/gage_climate.csv, is
committed to the repository, so the cluster jobs never need the shapefile.

    python scripts/00_assign_climate.py --gages gages.csv --zones Aridity_zones/AZ.shp

Input  gages.csv   from AGU26_QPE_CFE_results.zip (site, lat, lon, ...)
       AZ.shp      from Aridity_zones.rar: four polygons (EPSG:4326) with the
                   fields name (humid, subhumid, semiarid, arid) and value
Rule   the zone that contains the gage location. A gage outside every polygon
       (coast line) takes the nearest polygon and is flagged in the column
       assigned_by.
"""
import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

LABEL = {"arid": "Arid", "semiarid": "Semi-arid", "subhumid": "Semi-humid", "humid": "Humid"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gages", required=True)
    ap.add_argument("--zones", required=True)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "static" / "gage_climate.csv"))
    a = ap.parse_args()

    g = pd.read_csv(a.gages, dtype={"site": str})
    pts = gpd.GeoDataFrame(g[["site", "lat", "lon"]], geometry=gpd.points_from_xy(g["lon"], g["lat"]), crs="EPSG:4326")
    z = gpd.read_file(a.zones).to_crs("EPSG:4326")
    z["geometry"] = z.geometry.make_valid()
    z = z[["name", "value", "geometry"]].rename(columns={"name": "zone_raw", "value": "zone_value"})

    j = gpd.sjoin(pts, z, how="left", predicate="within").drop(columns="index_right")
    j = j[~j["site"].duplicated(keep="first")].copy()
    j["assigned_by"] = "inside"
    out = j["zone_raw"].isna()
    if out.any():
        # nearest polygon, distances in an equal-area projection of CONUS
        near = gpd.sjoin_nearest(pts[pts["site"].isin(j.loc[out, "site"])].to_crs("EPSG:5070"),
                                 z.to_crs("EPSG:5070"), how="left").drop_duplicates("site").set_index("site")
        for c in ["zone_raw", "zone_value"]:
            j.loc[out, c] = j.loc[out, "site"].map(near[c]).to_numpy()
        j.loc[out, "assigned_by"] = "nearest"
    j["aridity_zone"] = j["zone_raw"].map(LABEL)
    res = j[["site", "aridity_zone", "zone_raw", "zone_value", "assigned_by"]].sort_values("site")
    res.to_csv(a.out, index=False)
    print(res["aridity_zone"].value_counts().to_string())
    print(res["assigned_by"].value_counts().to_string())
    print("written", a.out, len(res))


if __name__ == "__main__":
    main()
