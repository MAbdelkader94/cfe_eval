"""
qaqc.py - quality control statistics of the observed and simulated hourly flow.

compute_stats() reads the organized time series of every gage once and returns
one row per gage with simple, transparent numbers: data coverage, zero flow,
flat lines, runoff depth, extreme peaks, and whether the three model runs
differ at all. The table is cached in results/tables/qaqc_stats, so the
notebook only waits the first time.

All statistics use the scoring window (config.START to config.END).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import common as cm
from . import config as cfg

SECONDS_PER_YEAR = 365.25 * 86400
FLAT_RUN_H = 120          # a flat line = the same value for at least 5 days


def longest_run(mask: np.ndarray) -> int:
    """Length of the longest run of True values."""
    if not mask.any():
        return 0
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return int((np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)).max())


def frac_in_long_runs(same_as_previous: np.ndarray, min_len: int) -> float:
    """Share of time steps that sit inside a run of repeated values of at least min_len steps."""
    if len(same_as_previous) == 0:
        return np.nan
    edges = np.diff(np.concatenate(([0], same_as_previous.astype(np.int8), [0])))
    lengths = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
    return float(lengths[lengths >= min_len - 1].sum() / len(same_as_previous))


def runoff_mm_per_year(mean_cms: float, area_km2: float) -> float:
    return mean_cms * SECONDS_PER_YEAR / (area_km2 * 1e6) * 1000.0


def site_stats(site: str, area_km2: float) -> dict:
    df = cm.read_timeseries(site)
    n = len(df)
    raw, obs = df["obs_cms"].to_numpy(float), df["obs_scoring_cms"].to_numpy(float)
    ok = np.isfinite(obs)
    o = obs[ok]
    row = {"gage": site, "hours_window": n,
           # observed flow
           "obs_coverage": float(ok.mean()),                       # after gap filling
           "obs_raw_coverage": float(np.isfinite(raw).mean()),     # before gap filling
           "obs_longest_gap_days": longest_run(~np.isfinite(raw)) / 24.0,
           "obs_zero_frac": float((o == 0).mean()) if len(o) else np.nan,
           "obs_mean_cms": float(o.mean()) if len(o) else np.nan,
           "obs_max_cms": float(o.max()) if len(o) else np.nan,
           "obs_distinct_values": int(len(np.unique(o))),
           # share of hours inside flat lines (same non-zero value for 5 days or more)
           "obs_flat_frac": frac_in_long_runs((np.diff(o) == 0) & (o[1:] > 0), FLAT_RUN_H) if len(o) > 1 else np.nan}
    row["obs_runoff_mm_yr"] = runoff_mm_per_year(row["obs_mean_cms"], area_km2)
    row["obs_unit_peak_cms_km2"] = row["obs_max_cms"] / area_km2
    sims = {}
    for prod in cfg.PRODUCTS:
        s = df[prod].to_numpy(float)
        sims[prod] = s
        fin = np.isfinite(s)
        v = s[fin]
        row[f"sim_missing_frac_{prod}"] = float(1 - fin.mean())
        row[f"sim_negative_hours_{prod}"] = int((v < 0).sum())
        row[f"sim_zero_frac_{prod}"] = float((v == 0).mean()) if len(v) else np.nan
        row[f"sim_near_zero_frac_{prod}"] = float((v < 1e-4).mean()) if len(v) else np.nan    # below 0.1 L/s
        row[f"sim_longest_zero_days_{prod}"] = longest_run(fin & (s == 0)) / 24.0
        row[f"sim_mean_cms_{prod}"] = float(v.mean()) if len(v) else np.nan
        row[f"sim_max_cms_{prod}"] = float(v.max()) if len(v) else np.nan
        row[f"sim_constant_{prod}"] = bool(len(v) and v.std() == 0)
        row[f"sim_runoff_mm_yr_{prod}"] = runoff_mm_per_year(row[f"sim_mean_cms_{prod}"], area_km2)
        row[f"sim_unit_peak_cms_km2_{prod}"] = row[f"sim_max_cms_{prod}"] / area_km2
        both = ok & fin
        row[f"sim_to_obs_mean_ratio_{prod}"] = float(s[both].mean() / obs[both].mean()) \
            if both.any() and obs[both].mean() > 0 else np.nan
    # do the three runs differ? identical series would mean the rain was not replaced
    for a, b in [("MRMS_P2", "AORC"), ("MRMS_RO", "AORC"), ("MRMS_RO", "MRMS_P2")]:
        row[f"identical_frac_{a}_vs_{b}"] = float((sims[a] == sims[b]).mean())
    return row


def compute_stats(force: bool = False, progress: bool = True) -> pd.DataFrame:
    """One row per gage. Cached in results/tables/qaqc_stats.(parquet, csv)."""
    cache = cfg.TABLES / "qaqc_stats.parquet"
    if not force and (cache.exists() or cache.with_suffix(".csv").exists()):
        return cm.read_table("qaqc_stats")
    gages = cm.read_gages()
    rows = []
    for i, (site, area) in enumerate(zip(gages["site"], gages["area_km2"]), 1):
        rows.append(site_stats(site, float(area)))
        if progress and (i % 100 == 0 or i == len(gages)):
            print(f"  quality statistics: {i}/{len(gages)} gages", flush=True)
    out = cm.with_attrs(pd.DataFrame(rows), gages)
    cm.write_table(out, "qaqc_stats")
    return out


# --------------------------------------------------------------------------
# screening rules
# --------------------------------------------------------------------------
# Each rule: a threshold, whether a flagged gage is dropped (drop=True) or only
# marked for inspection (drop=False), and the reason in plain words. By default
# every rule drops its gages, so the analysis uses only gages that pass all checks.
# The quality control notebook copies this dictionary so every value can be changed there.
DEFAULT_RULES = {
    "model_output_invalid": {
        "drop": True,
        "why": "simulated flow has missing or negative values, or never changes"},
    "runs_identical": {
        "max_identical_frac": 0.99, "drop": True,
        "why": "two model runs give the same flow almost every hour, so the rain was probably not replaced"},
    "obs_coverage_low": {
        "min_coverage": 0.75, "drop": True,
        "why": "observed flow covers less than this share of the scoring window"},
    "obs_runoff_implausible": {
        "max_mm_yr": 2000.0, "drop": True,
        "why": "observed mean flow divided by the drainage area exceeds this depth per year "
               "(wrong area, water imported into the basin, or a canal)"},
    "sim_runoff_implausible": {
        "max_mm_yr": 2000.0, "drop": True,
        "why": "simulated mean flow divided by the USGS drainage area exceeds this depth per year "
               "(the model outlet drains a much larger area than the gage)"},
    "obs_flat_lines": {
        "max_flat_frac": 0.05, "drop": True,
        "why": "more than this share of observed hours sit in flat lines of 5 days or longer "
               "(regulated releases, ice, or estimated record)"},
    "obs_mostly_dry": {
        "max_zero_frac": 0.50, "drop": True,
        "why": "the observed stream has zero flow more than this share of the time (ephemeral stream); "
               "scores divided by the mean flow become unstable"},
    "sim_mostly_dry": {
        "max_zero_frac": 0.50, "drop": True,
        "why": "a model run has zero flow more than this share of the time"},
    "volume_mismatch": {
        "min_ratio": 0.1, "max_ratio": 10.0, "drop": True,
        "why": "simulated mean flow is below min_ratio or above max_ratio times the observed mean flow "
               "with all three rain products (not a rain problem: regulation, diversion, wrong area, or model)"},
    "few_observed_events": {
        "min_events": 13, "drop": True,
        "why": "fewer observed events than needed for the larger-flood threshold (13th largest event)"},
}


def apply_rules(stats: pd.DataFrame, gages: pd.DataFrame, rules: dict | None = None) -> pd.DataFrame:
    """One row per gage: one True/False column per rule, keep, and the reasons a gage is dropped.

    stats: table of compute_stats(); gages: the merged gages table (for obs_events_all)."""
    rules = rules or DEFAULT_RULES
    s = stats.set_index("gage")
    P = list(cfg.PRODUCTS)
    col = lambda name: s[[f"{name}_{p}" for p in P]]                      # noqa: E731
    ratio = col("sim_to_obs_mean_ratio")
    ident = s[[c for c in s.columns if c.startswith("identical_frac_")]]
    n_events = gages.set_index("site")["obs_events_all"].reindex(s.index)
    r = rules
    flags = pd.DataFrame({
        "model_output_invalid": (col("sim_missing_frac") > 0).any(axis=1) | (col("sim_negative_hours") > 0).any(axis=1)
                                | col("sim_constant").any(axis=1),
        "runs_identical": (ident > r["runs_identical"]["max_identical_frac"]).any(axis=1),
        "obs_coverage_low": s["obs_coverage"] < r["obs_coverage_low"]["min_coverage"],
        "obs_runoff_implausible": s["obs_runoff_mm_yr"] > r["obs_runoff_implausible"]["max_mm_yr"],
        "sim_runoff_implausible": (col("sim_runoff_mm_yr") > r["sim_runoff_implausible"]["max_mm_yr"]).any(axis=1),
        "obs_flat_lines": s["obs_flat_frac"] > r["obs_flat_lines"]["max_flat_frac"],
        "obs_mostly_dry": s["obs_zero_frac"] > r["obs_mostly_dry"]["max_zero_frac"],
        "sim_mostly_dry": (col("sim_zero_frac") > r["sim_mostly_dry"]["max_zero_frac"]).any(axis=1),
        "volume_mismatch": (ratio < r["volume_mismatch"]["min_ratio"]).all(axis=1)
                           | (ratio > r["volume_mismatch"]["max_ratio"]).all(axis=1),
        "few_observed_events": n_events < r["few_observed_events"]["min_events"],
    }).astype(bool)
    dropping = [k for k in flags.columns if rules[k]["drop"]]
    flags["keep"] = ~flags[dropping].any(axis=1)
    flags["drop_reasons"] = [", ".join(k for k in dropping if row[k]) for _, row in flags.iterrows()]
    flags["flags_only"] = [", ".join(k for k in flags.columns[:-2] if k not in dropping and row[k])
                           for _, row in flags.iterrows()]
    return flags.reset_index()
