"""
common.py - small helpers shared by the step scripts: reading the organized
data, seasons and water years, the gage slice of an array task, table output.
"""
from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as cfg


# --------------------------------------------------------------------------
# organized data
# --------------------------------------------------------------------------
def read_gages() -> pd.DataFrame:
    """organized/gages.csv: one row per gage with all attributes."""
    return pd.read_csv(cfg.ORGANIZED / "gages.csv", dtype={"site": str})


def read_timeseries(site: str, window: bool = True) -> pd.DataFrame:
    """Hourly flow of one gage: obs_cms, obs_scoring_cms, AORC, MRMS_P2, MRMS_RO
    (m3/s) on a tz-aware UTC index. window=True keeps the scoring window only."""
    df = pd.read_parquet(cfg.ORGANIZED / "timeseries" / f"{site}.parquet")
    df.index = pd.DatetimeIndex(df.index).tz_localize("UTC") if df.index.tz is None else df.index
    df.index.name = "time_utc"
    if window:
        df = df.loc[pd.Timestamp(cfg.START, tz="UTC"):pd.Timestamp(cfg.END, tz="UTC")]
    return df


def read_gaps() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """MRMS gaps longer than 3 h that touch the scoring window, as (start - 1 h, end).
    Rain was set to zero there, so events overlapping a gap are not scored."""
    f = cfg.ORGANIZED / "mrms_long_gaps.csv"
    t0, t1 = pd.Timestamp(cfg.START, tz="UTC"), pd.Timestamp(cfg.END, tz="UTC")
    gaps = []
    if f.exists():
        for _, r in pd.read_csv(f).iterrows():
            s, e = pd.Timestamp(r["start_utc"], tz="UTC"), pd.Timestamp(r["end_utc"], tz="UTC")
            if e >= t0 and s <= t1:
                gaps.append((s - pd.Timedelta("1h"), e))
    return sorted(set(gaps))


# --------------------------------------------------------------------------
# time labels
# --------------------------------------------------------------------------
def season_of(t) -> np.ndarray:
    """Season name of each time stamp (Winter = Dec, Jan, Feb, and so on)."""
    return pd.DatetimeIndex(t).month.map(cfg.SEASON_OF_MONTH).to_numpy()


def water_year_of(t) -> np.ndarray:
    """Water year of each time stamp (WY 2022 = Oct 2021 to Sep 2022)."""
    t = pd.DatetimeIndex(t)
    return (t.year + (t.month >= 10)).to_numpy()


def add_time_labels(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Add season, month and water_year columns from the time column col."""
    t = pd.DatetimeIndex(pd.to_datetime(df[col], utc=True))
    df["season"] = season_of(t)
    df["month"] = t.month
    df["water_year"] = water_year_of(t)
    return df


# --------------------------------------------------------------------------
# array tasks and per-gage part files
# --------------------------------------------------------------------------
def task_args(description: str) -> argparse.Namespace:
    """Command line shared by steps 2 to 4.

    --task K --ntasks N   this process handles gages K, K+N, K+2N, ... (K from 1,
                          as in $SGE_TASK_ID). Default: one task with every gage.
    --limit M             only the first M gages (smoke test)
    --force               recompute gages that already have a part file
    """
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--task", type=int, default=1)
    ap.add_argument("--ntasks", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    return ap.parse_args()


def my_sites(a: argparse.Namespace) -> list[str]:
    sites = read_gages()["site"].tolist()
    if a.limit:
        sites = sites[: a.limit]
    return sites[a.task - 1::a.ntasks]


def part_path(step: str, site: str) -> Path:
    return cfg.PARTS / step / f"{site}.pkl"


def save_part(step: str, site: str, obj: dict) -> None:
    """Write a part file atomically, so a killed task never leaves half a file."""
    p = part_path(step, site)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f)
    tmp.replace(p)


def load_part(step: str, site: str) -> dict:
    with open(part_path(step, site), "rb") as f:
        return pickle.load(f)


def run_sites(step: str, a: argparse.Namespace, func) -> int:
    """Run func(site) -> dict for every gage of this task; one part file per gage.
    A failure is stored in the part file (key error) and reported at the end.
    Returns the number of failed gages."""
    import time
    import traceback
    sites = my_sites(a)
    print(f"step {step}: task {a.task}/{a.ntasks}, {len(sites)} gages", flush=True)
    failed = 0
    for n, site in enumerate(sites, 1):
        if part_path(step, site).exists() and not a.force:
            if not load_part(step, site).get("error"):
                continue
        t = time.time()
        try:
            res = func(site)
            res["error"] = None
        except Exception:  # noqa: BLE001
            res = {"error": traceback.format_exc()}
            failed += 1
        save_part(step, site, res)
        note = "OK" if res["error"] is None else "ERROR " + res["error"].strip().splitlines()[-1][:150]
        print(f"[{n}/{len(sites)}] {site} {note} ({time.time() - t:.1f} s)", flush=True)
    print(f"step {step}: task {a.task} finished, {failed} failed", flush=True)
    return failed


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------
GAGE_ATTRS = ["aridity_zone", "area_km2", "area_class", "state_tag"]


def with_attrs(df: pd.DataFrame, gages: pd.DataFrame) -> pd.DataFrame:
    """Add the gage attributes used for grouping (climate zone, area, state)."""
    if df.empty:
        return df
    return df.merge(gages[["site"] + GAGE_ATTRS].rename(columns={"site": "gage"}), on="gage", how="left")


def write_table(df: pd.DataFrame, name: str) -> None:
    """results/tables/<name>.parquet and <name>.csv (times as UTC text)."""
    cfg.TABLES.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cfg.TABLES / f"{name}.parquet", index=False)
    df.to_csv(cfg.TABLES / f"{name}.csv", index=False)
    print(f"  {name}: {len(df):,} rows, {len(df.columns)} columns", flush=True)


def read_table(name: str) -> pd.DataFrame:
    return pd.read_parquet(cfg.TABLES / f"{name}.parquet")
