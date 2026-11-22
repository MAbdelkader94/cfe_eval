"""
01_organize.py - step 1: turn AGU26_QPE_CFE_results.zip into an analysis-ready
folder. Nothing is computed here; the data are only checked and rearranged.

    python scripts/01_organize.py                 (all 818 gages)
    python scripts/01_organize.py --limit 5       (smoke test)

Reads   <data root>/AGU26_QPE_CFE_results.zip
        static/gage_climate.csv                   aridity zone per gage
Writes  <data root>/organized/
    gages.csv                 one row per gage: USGS attributes, outlet reach, aridity
                              zone, area class, larger-flood threshold of the package
    timeseries/<site>.parquet hourly UTC, 2020-10-15 01:00 to 2025-12-31 00:00, columns
                              obs_cms          observed, hour ending at T
                              obs_scoring_cms  observed, scoring window, gaps <= 24 h filled
                              AORC, MRMS_P2, MRMS_RO   simulated outlet flow (float32,
                              the precision of the t-route output)
    mrms_long_gaps.csv        MRMS gaps > 3 h (product, start_utc, end_utc, hours)
    package_eval/             evaluation tables shipped in the package (reference for
                              scripts/check_against_package.py)
    package_docs/             README.md, DATA_GUIDE.md, gage_accounting.csv, scripts
    manifest.json             what was written and the checks that passed
Checks  MD5 of every item against MD5SUMS.txt; every series has the full hourly axis.
Restart safe: gages whose parquet file exists are skipped (use --force to redo).
"""
import _path  # noqa: F401
import argparse
import hashlib
import json
import shutil
import time
import zipfile

import numpy as np
import pandas as pd

from cfe_eval import config as cfg

T_FIRST, T_LAST, N_HOURS = "2020-10-15 01:00", "2025-12-31 00:00", 45672


def md5(path, chunk=1 << 24):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def read_series(zf, member, col):
    df = pd.read_csv(zf.open(member))
    if len(df) != N_HOURS or df["time_utc"].iloc[0] != T_FIRST or df["time_utc"].iloc[-1] != T_LAST:
        raise RuntimeError(f"{member}: unexpected time axis ({len(df)} rows, "
                           f"{df['time_utc'].iloc[0]} to {df['time_utc'].iloc[-1]})")
    return df[col] if isinstance(col, list) else df[col].to_numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skip-md5", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    org, tmp = cfg.ORGANIZED, cfg.ORGANIZED / "_unzipped"
    (org / "timeseries").mkdir(parents=True, exist_ok=True)
    if not cfg.PACKAGE_ZIP.exists():
        raise SystemExit(f"ERROR: package not found: {cfg.PACKAGE_ZIP}")

    # 1. unpack the outer zip (it holds one zip per product) and check the MD5 sums
    print(f"unpacking {cfg.PACKAGE_ZIP}", flush=True)
    with zipfile.ZipFile(cfg.PACKAGE_ZIP) as z:
        for n in z.namelist():
            if not (tmp / n).exists():
                z.extract(n, tmp)
    md5_ok = None
    if not a.skip_md5:
        md5_ok = True
        for line in (tmp / "MD5SUMS.txt").read_text().splitlines():
            if not line.strip():
                continue
            want, name = line.split(None, 1)
            got = md5(tmp / name.strip())
            if got != want:
                md5_ok = False
                print(f"  MD5 MISMATCH {name}: {got} != {want}", flush=True)
        if not md5_ok:
            raise SystemExit("ERROR: the package is damaged (MD5 mismatch); copy it again")
        print("  MD5 sums OK", flush=True)

    # 2. gage table with the grouping attributes
    g = pd.read_csv(tmp / "gages.csv", dtype={"site": str})
    clim = pd.read_csv(cfg.CLIMATE_CSV, dtype={"site": str})
    g = g.merge(clim[["site", "aridity_zone", "assigned_by"]].rename(columns={"assigned_by": "aridity_assigned_by"}),
                on="site", how="left")
    if g["aridity_zone"].isna().any():
        raise SystemExit(f"ERROR: {g['aridity_zone'].isna().sum()} gages have no aridity zone; "
                         "run scripts/00_assign_climate.py")
    g["area_class"] = pd.cut(g["area_km2"], cfg.AREA_BINS, labels=cfg.AREA_LABELS).astype(str)
    g = g.rename(columns={"event_threshold_cms": "package_event_threshold_cms"})
    g.to_csv(org / "gages.csv", index=False)
    sites = g["site"].tolist()[: a.limit or None]

    # 3. one parquet file per gage
    zsim = {k: zipfile.ZipFile(tmp / f"{d}.zip") for k, d in cfg.PRODUCTS.items()}
    zobs = zipfile.ZipFile(tmp / "04_USGS_observed.zip")
    index = pd.date_range(T_FIRST, T_LAST, freq="1h", name="time_utc")
    assert len(index) == N_HOURS
    done = 0
    for n, site in enumerate(sites, 1):
        out = org / "timeseries" / f"{site}.parquet"
        if out.exists() and not a.force:
            continue
        obs = read_series(zobs, f"04_USGS_observed/hourly/{site}.csv", ["obs_cms", "obs_scoring_cms"])
        df = pd.DataFrame({"obs_cms": obs["obs_cms"].to_numpy(float),
                           "obs_scoring_cms": obs["obs_scoring_cms"].to_numpy(float)}, index=index)
        for k, d in cfg.PRODUCTS.items():
            df[k] = read_series(zsim[k], f"{d}/flows/{site}.csv", "flow_cms").astype(np.float32)
        tmpf = out.with_suffix(".tmp")
        df.to_parquet(tmpf)
        tmpf.replace(out)
        done += 1
        if n % 50 == 0 or n == len(sites):
            print(f"  [{n}/{len(sites)}] time series written ({time.time() - t0:.0f} s)", flush=True)

    # 4. MRMS gaps, reference tables and documents
    gaps = []
    for k, d in cfg.PRODUCTS.items():
        for m in zsim[k].namelist():
            if "long_gaps" in m:
                x = pd.read_csv(zsim[k].open(m))
                x.insert(0, "product", k)
                gaps.append(x)
            elif "/eval_" in m and m.endswith(".csv"):
                dst = org / "package_eval" / m.split("/")[1] / m.split("/")[2]
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(zsim[k].read(m))
    pd.concat(gaps, ignore_index=True).to_csv(org / "mrms_long_gaps.csv", index=False)
    docs = org / "package_docs"
    docs.mkdir(exist_ok=True)
    for n in ["README.md", "DATA_GUIDE.md", "gage_accounting.csv", "05_scripts.zip"]:
        shutil.copy2(tmp / n, docs / n)
    for z in list(zsim.values()) + [zobs]:
        z.close()

    have = sum((org / "timeseries" / f"{s}.parquet").exists() for s in sites)
    manifest = {"package": str(cfg.PACKAGE_ZIP), "md5_ok": md5_ok, "gages_in_package": len(g),
                "gages_requested": len(sites), "timeseries_files": have, "hours_per_series": N_HOURS,
                "first_hour_utc": T_FIRST, "last_hour_utc": T_LAST,
                "aridity_zones": g["aridity_zone"].value_counts().to_dict(),
                "area_classes": g["area_class"].value_counts().to_dict()}
    (org / "manifest.json").write_text(json.dumps(manifest, indent=2))
    if have == len(sites):
        shutil.rmtree(tmp)          # the unpacked copy is no longer needed
    print(json.dumps(manifest, indent=2))
    print(f"organized: {have}/{len(sites)} gages ({done} new) in {time.time() - t0:.0f} s -> {org}", flush=True)
    if have != len(sites):
        raise SystemExit("ERROR: some time series are missing")


if __name__ == "__main__":
    main()
