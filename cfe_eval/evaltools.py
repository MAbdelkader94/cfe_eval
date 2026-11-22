"""
evaltools.py - event based evaluation of a NextGen (t-route) hydrograph
against USGS observations. Team "Don't Runoff!", RUNOFF, Summer Institute 2026.

The three notebooks in this folder call these functions in order:

    01_prepare_data.ipynb    load_troute_outlet, load_usgs_hourly, pair_series
    02_event_matching.ipynb  detect_events, filter_events, match_events, contingency
    03_metrics.ipynb         event_metrics, continuous_metrics, summarize

Units: discharge in m3/s everywhere (t-route writes m3/s; USGS cfs is converted
on load). Times are UTC. Drainage area in km2 is only needed for runoff depth
in mm and for the unit peak threshold.

Method (team decision, July 2026, see Eval_final/README.md in the team folder):
  1. hydrograph separation with NOAA-OWP hydrotools, same settings for the
     observed and the simulated series
  2. keep events above a size threshold (unit peak in m3/s per km2)
  3. match one to one; a simulated event is a candidate when it touches the
     window observed peak +/- 12 h and its own peak is within 12 h; the best
     candidate has the lowest cost = 0.7 * |dt|/12 + 0.3 * |ln(Qsim/Qobs)|
  4. unmatched observed events are misses, unmatched simulated events are
     false alarms -> POD, FAR, CSI
  5. per matched pair: peak error (%), time to peak error (h), volume error (%),
     rise time, Richards-Baker flashiness; plus RMSE, PBIAS, NSE, NNSE, KGE on
     the full hourly series
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

CFS_TO_CMS = 0.0283168466
SQMI_TO_KM2 = 2.589988


def _utc(x) -> pd.Timestamp:
    """Any date-like value as a UTC Timestamp."""
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


# --------------------------------------------------------------------------
# 1. loading
# --------------------------------------------------------------------------
def describe_troute(nc_path) -> pd.DataFrame:
    """One row per feature in a t-route output file: mean, max flow and the
    share of hours with flow above zero. Sorted by mean flow, so the outlet
    (where the whole basin drains) is the first row."""
    import xarray as xr
    with xr.open_dataset(nc_path) as ds:
        flow = ds["flow"]
        df = pd.DataFrame({
            "feature_id": ds["feature_id"].values,
            "mean_cms": flow.mean("time").values,
            "max_cms": flow.max("time").values,
            "frac_flowing": (flow > 0).mean("time").values,
        })
        df.attrs["start"] = pd.Timestamp(ds["time"].values[0])
        df.attrs["end"] = pd.Timestamp(ds["time"].values[-1])
        df.attrs["n_hours"] = int(ds.sizes["time"])
    return df.sort_values("mean_cms", ascending=False).reset_index(drop=True)


def load_troute_outlet(nc_path, feature_id=None) -> tuple[pd.Series, int]:
    """Hourly simulated discharge (m3/s) at one feature of a t-route file.

    feature_id=None picks the feature with the largest mean flow. In a single
    gage NGIAB subset that is the outlet segment, where the gage sits.
    Returns (series with tz-aware UTC index, feature_id used).
    """
    import xarray as xr
    with xr.open_dataset(nc_path) as ds:
        flow = ds["flow"]
        if feature_id is None:
            feature_id = int(ds["feature_id"].values[int(flow.mean("time").argmax())])
        s = flow.sel(feature_id=feature_id).to_series().astype(float)
    s.index = pd.to_datetime(s.index).tz_localize("UTC")
    s = s[~s.index.duplicated(keep="first")].sort_index()
    s.name = "sim_cms"
    return s, int(feature_id)


def site_info(gage: str) -> dict:
    """Station name, coordinates and drainage area (km2) from USGS NWIS."""
    from dataretrieval import nwis
    info, _ = nwis.get_info(sites=gage)
    r = info.iloc[0]
    area_sqmi = float(r.get("drain_area_va", np.nan))
    return {"gage": gage, "name": str(r["station_nm"]),
            "lat": float(r["dec_lat_va"]), "lon": float(r["dec_long_va"]),
            "area_km2": area_sqmi * SQMI_TO_KM2 if np.isfinite(area_sqmi) else np.nan}


def load_usgs_hourly(gage: str, start, end, cache_dir="data") -> pd.Series:
    """Observed discharge from USGS NWIS (parameter 00060, instantaneous),
    converted to m3/s and averaged to hourly steps, UTC. The download is
    cached as data/obs_<gage>.csv.gz so the notebooks work offline afterwards."""
    cache = Path(cache_dir) / f"obs_{gage}.csv.gz"
    if cache.exists():
        s = pd.read_csv(cache, index_col=0, parse_dates=True)["obs_cms"]
        s.index = pd.to_datetime(s.index, utc=True)
        return s
    from dataretrieval import nwis
    start = pd.Timestamp(start).strftime("%Y-%m-%dT%H:%MZ")
    end = pd.Timestamp(end).strftime("%Y-%m-%dT%H:%MZ")
    df, _ = nwis.get_iv(sites=gage, parameterCd="00060", start=start, end=end)
    if df is None or len(df) == 0 or "00060" not in df.columns:
        raise RuntimeError(f"no discharge returned for USGS {gage}")
    q = df["00060"].astype(float)
    q.index = q.index.tz_convert("UTC")
    q = q[~q.index.duplicated(keep="first")].sort_index()
    q[q < 0] = np.nan                              # -999999 flags
    s = (q * CFS_TO_CMS).resample("1h").mean().rename("obs_cms")
    cache.parent.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_csv(cache, compression="gzip")
    return s


def pair_series(obs: pd.Series, sim: pd.Series, start=None, end=None,
                max_gap_h: int = 24) -> pd.DataFrame:
    """Put observed and simulated flow on one hourly UTC index.

    The common period is the overlap of the two series unless start/end are
    given. Observation gaps up to max_gap_h hours are linearly interpolated
    and flagged in the column obs_filled; longer gaps stay NaN.
    """
    t0 = max(obs.index.min(), sim.index.min()) if start is None else _utc(start)
    t1 = min(obs.index.max(), sim.index.max()) if end is None else _utc(end)
    idx = pd.date_range(t0.floor("h"), t1.floor("h"), freq="1h", tz="UTC")
    df = pd.DataFrame({"obs_cms": obs.reindex(idx), "sim_cms": sim.reindex(idx)})
    df["obs_filled"] = df["obs_cms"].isna()
    df["obs_cms"] = df["obs_cms"].interpolate(limit=max_gap_h, limit_area="inside")
    df["obs_filled"] &= df["obs_cms"].notna()
    df.index.name = "time_utc"
    return df


# --------------------------------------------------------------------------
# 2. hydrograph separation
# --------------------------------------------------------------------------
def detect_events(series: pd.Series, halflife="6h", window="7D",
                  minimum_event_duration="6h", start_radius="0h") -> pd.DataFrame:
    """Split a hydrograph into events with the NOAA-OWP hydrotools
    decomposition (exponential smoothing with the given halflife, rolling
    minimum baseflow over the window, events shorter than
    minimum_event_duration dropped). Use the SAME settings on observed and
    simulated flow.

    Returns one row per event: start, end, t_peak, peak, q_start, rise_h,
    duration_h, volume_m3.
    """
    from hydrotools.events.event_detection import decomposition as ev
    s = series.dropna()
    flags = ev.mark_event_flows(s, halflife=halflife, window=window,
                                minimum_event_duration=minimum_event_duration,
                                start_radius=start_radius).astype(bool)
    fwd = flags.shift(1, fill_value=False).astype(bool)
    bwd = flags.shift(-1, fill_value=False).astype(bool)
    starts, ends = flags.index[flags & ~fwd], flags.index[flags & ~bwd]
    rows = []
    for a, b in zip(starts, ends):
        seg = s.loc[a:b]
        if len(seg) < 2:
            continue
        t_peak = seg.idxmax()
        rows.append({"start": a, "end": b, "t_peak": t_peak, "peak": float(seg.max()),
                     "q_start": float(seg.iloc[0]),
                     "rise_h": (t_peak - a).total_seconds() / 3600.0,
                     "duration_h": (b - a).total_seconds() / 3600.0,
                     "volume_m3": volume_m3(s, a, b)})
    cols = ["start", "end", "t_peak", "peak", "q_start", "rise_h", "duration_h", "volume_m3"]
    return pd.DataFrame(rows, columns=cols)


def filter_events(events: pd.DataFrame, area_km2=None, min_unit_peak=0.001,
                  min_peak_cms=0.0) -> pd.DataFrame:
    """Drop small events. Default: unit peak (peak / area) below 0.001 m3/s
    per km2, which removes baseflow wiggles the detector flags as events.
    Without an area, min_peak_cms is used alone."""
    if events.empty:
        return events.copy()
    keep = events["peak"] >= min_peak_cms
    if area_km2 and np.isfinite(area_km2):
        keep &= events["peak"] / area_km2 >= min_unit_peak
    return events[keep].reset_index(drop=True)


# --------------------------------------------------------------------------
# 3. matching
# --------------------------------------------------------------------------
def match_events(obs_events: pd.DataFrame, sim_events: pd.DataFrame,
                 window_h: float = 12.0, w_time: float = 0.7, w_mag: float = 0.3,
                 guard_frac: float = 0.05) -> pd.DataFrame:
    """Pair observed and simulated events one to one (team Strategy 6).

    A simulated event is a candidate for an observed event when
      * it touches the window [obs peak - window_h, obs peak + window_h]
        (for a late simulation: it starts within window_h after the observed
        peak; a simulation already in flood at the observed peak qualifies)
      * its peak is within window_h of the observed peak
      * its peak is at least guard_frac of the observed peak
    Among candidates the lowest cost wins:
      cost = w_time * min(|dt| / window_h, 2) + w_mag * |ln(Qsim / Qobs)|
    Assignment is greedy on ascending cost, each event used once.

    Returns one row per observed event with status hit or miss and, for hits,
    the matched sim index, peak, peak time and dt_h = t_peak_sim - t_peak_obs.
    """
    pairs = []
    for i, e in obs_events.iterrows():
        for j, s in sim_events.iterrows():
            late_h = (s["start"] - e["t_peak"]).total_seconds() / 3600.0
            ended_h = (e["t_peak"] - s["end"]).total_seconds() / 3600.0
            if late_h > window_h or ended_h > window_h:
                continue
            dt = (s["t_peak"] - e["t_peak"]).total_seconds() / 3600.0
            if abs(dt) > window_h or s["peak"] < guard_frac * e["peak"]:
                continue
            cost = (w_time * min(abs(dt) / window_h, 2.0)
                    + w_mag * abs(np.log(max(s["peak"], 1e-9) / max(e["peak"], 1e-9))))
            pairs.append((cost, i, j))
    used_obs, used_sim, chosen = set(), set(), {}
    for cost, i, j in sorted(pairs):
        if i in used_obs or j in used_sim:
            continue
        chosen[i] = (j, cost)
        used_obs.add(i)
        used_sim.add(j)
    rows = []
    for i, e in obs_events.iterrows():
        row = {"obs_idx": i, "t_peak_obs": e["t_peak"], "peak_obs": e["peak"],
               "status": "miss", "sim_idx": np.nan, "t_peak_sim": pd.NaT,
               "peak_sim": np.nan, "dt_h": np.nan, "cost": np.nan}
        if i in chosen:
            j, cost = chosen[i]
            s = sim_events.loc[j]
            row.update({"status": "hit", "sim_idx": j, "t_peak_sim": s["t_peak"],
                        "peak_sim": s["peak"],
                        "dt_h": (s["t_peak"] - e["t_peak"]).total_seconds() / 3600.0,
                        "cost": cost})
        rows.append(row)
    out = pd.DataFrame(rows)
    out.attrs["n_sim_events"] = len(sim_events)
    return out


def contingency(matches: pd.DataFrame, n_sim_events: int) -> dict:
    """Hits, misses, false alarms and POD = H/(H+M), FAR = FA/(H+FA),
    CSI = H/(H+M+FA). A false alarm is a simulated event matched to nothing."""
    hits = int((matches["status"] == "hit").sum())
    miss = int((matches["status"] == "miss").sum())
    fa = max(n_sim_events - hits, 0)
    return {"hits": hits, "misses": miss, "false_alarms": fa,
            "POD": hits / (hits + miss) if hits + miss else np.nan,
            "FAR": fa / (hits + fa) if hits + fa else np.nan,
            "CSI": hits / (hits + miss + fa) if hits + miss + fa else np.nan}


# --------------------------------------------------------------------------
# 4. metrics
# --------------------------------------------------------------------------
def volume_m3(series: pd.Series, start, end) -> float:
    """Event volume: trapezoid integral of discharge (m3/s) over time (s)."""
    s = series.loc[start:end].dropna()
    if len(s) < 2:
        return 0.0
    secs = (s.index - s.index[0]).total_seconds().to_numpy()
    y = s.to_numpy()
    return float(np.sum(0.5 * (y[1:] + y[:-1]) * np.diff(secs)))


def rb_flashiness(series: pd.Series, start, end) -> float:
    """Richards-Baker flashiness index over [start, end]:
    sum |Q(t) - Q(t-1)| / sum Q(t). Dimensionless."""
    s = series.loc[start:end].dropna().to_numpy()
    return float(np.abs(np.diff(s)).sum() / s.sum()) if s.sum() > 0 else np.nan


def event_metrics(obs: pd.Series, sim: pd.Series, obs_events: pd.DataFrame,
                  sim_events: pd.DataFrame, matches: pd.DataFrame,
                  area_km2=None) -> pd.DataFrame:
    """One row of metrics per matched pair (hits only).

    peak_err_pct      (Qpeak_sim - Qpeak_obs) / Qpeak_obs * 100
    time_to_peak_err_h  t_peak_sim - t_peak_obs (positive = simulation late)
    rise_obs_h, rise_sim_h   event start to peak, each series on its own event
    vol_err_pct       volume over the UNION of the two event windows, so a
                      shifted but otherwise correct event is not punished twice
    vol_obs_mm, vol_sim_mm   runoff depth when area_km2 is given
    rbi_obs, rbi_sim  Richards-Baker flashiness on the same window
    """
    rows = []
    for _, m in matches[matches["status"] == "hit"].iterrows():
        e = obs_events.loc[m["obs_idx"]]
        s = sim_events.loc[int(m["sim_idx"])]
        lo, hi = min(e["start"], s["start"]), max(e["end"], s["end"])
        v_obs, v_sim = volume_m3(obs, lo, hi), volume_m3(sim, lo, hi)
        row = {"t_peak_obs": e["t_peak"], "t_peak_sim": s["t_peak"],
               "peak_obs_cms": e["peak"], "peak_sim_cms": s["peak"],
               "peak_err_pct": (s["peak"] - e["peak"]) / e["peak"] * 100.0,
               "time_to_peak_err_h": m["dt_h"],
               "rise_obs_h": e["rise_h"], "rise_sim_h": s["rise_h"],
               "duration_obs_h": e["duration_h"], "duration_sim_h": s["duration_h"],
               "vol_obs_m3": v_obs, "vol_sim_m3": v_sim,
               "vol_err_pct": (v_sim - v_obs) / v_obs * 100.0 if v_obs > 0 else np.nan,
               "rbi_obs": rb_flashiness(obs, lo, hi), "rbi_sim": rb_flashiness(sim, lo, hi),
               "window_start": lo, "window_end": hi}
        if area_km2 and np.isfinite(area_km2):
            row["vol_obs_mm"] = v_obs / (area_km2 * 1e6) * 1000.0
            row["vol_sim_mm"] = v_sim / (area_km2 * 1e6) * 1000.0
        rows.append(row)
    return pd.DataFrame(rows)


def continuous_metrics(obs: pd.Series, sim: pd.Series) -> dict:
    """Whole-series scores on the hours where both values exist.

    RMSE   sqrt(mean((sim - obs)^2))                      m3/s
    NRMSE  RMSE / mean(obs) * 100                           %
    PBIAS  sum(sim - obs) / sum(obs) * 100                  %  (positive = too wet)
    NSE    1 - sum((sim - obs)^2) / sum((obs - mean(obs))^2)
    NNSE   1 / (2 - NSE), maps NSE to (0, 1]
    KGE    1 - sqrt((r - 1)^2 + (sd_sim/sd_obs - 1)^2 + (mean_sim/mean_obs - 1)^2)
    r      Pearson correlation
    """
    df = pd.concat([obs.rename("o"), sim.rename("s")], axis=1).dropna()
    o, s = df["o"].to_numpy(), df["s"].to_numpy()
    if len(o) < 2 or o.std() == 0:
        return {k: np.nan for k in ["n", "RMSE", "NRMSE_pct", "PBIAS_pct", "NSE", "NNSE", "KGE", "r"]}
    err = s - o
    nse = 1 - np.sum(err ** 2) / np.sum((o - o.mean()) ** 2)
    r = float(np.corrcoef(o, s)[0, 1])
    kge = 1 - np.sqrt((r - 1) ** 2 + (s.std() / o.std() - 1) ** 2 + (s.mean() / o.mean() - 1) ** 2)
    return {"n": int(len(o)), "RMSE": float(np.sqrt(np.mean(err ** 2))),
            "NRMSE_pct": float(np.sqrt(np.mean(err ** 2)) / o.mean() * 100),
            "PBIAS_pct": float(err.sum() / o.sum() * 100), "NSE": float(nse),
            "NNSE": float(1 / (2 - nse)), "KGE": float(kge), "r": r}


def summarize(metrics: pd.DataFrame, cols=("peak_err_pct", "time_to_peak_err_h",
                                            "vol_err_pct")) -> pd.DataFrame:
    """Median, interquartile range and mean absolute value of each metric."""
    rows = []
    for c in cols:
        v = metrics[c].dropna()
        rows.append({"metric": c, "n": len(v), "median": v.median(),
                     "q25": v.quantile(0.25), "q75": v.quantile(0.75),
                     "mean_abs": v.abs().mean()})
    return pd.DataFrame(rows).set_index("metric").round(2)


# --------------------------------------------------------------------------
# 5. plots
# --------------------------------------------------------------------------
def plot_events(obs: pd.Series, sim: pd.Series, obs_events=None, sim_events=None,
                matches=None, start=None, end=None, ax=None, title=None):
    """Observed (black) and simulated (blue) flow with observed events shaded,
    peaks marked and matched peaks joined by a dotted line."""
    import matplotlib.pyplot as plt
    if ax is None:
        _, ax = plt.subplots(figsize=(12, 4))
    start = _utc(start) if start is not None else None
    end = _utc(end) if end is not None else None
    o = obs.loc[start:end] if start or end else obs
    s = sim.loc[start:end] if start or end else sim
    ax.plot(o.index, o.values, color="black", lw=1.0, label="observed (USGS)")
    ax.plot(s.index, s.values, color="#5b8dd9", lw=1.0, label="simulated (t-route)")
    if obs_events is not None:
        for _, e in obs_events.iterrows():
            if (start is None or e["end"] >= start) and \
               (end is None or e["start"] <= end):
                ax.axvspan(e["start"], e["end"], color="grey", alpha=0.15)
                ax.plot(e["t_peak"], e["peak"], "v", color="black", ms=6)
    if sim_events is not None:
        for _, e in sim_events.iterrows():
            if (start is None or e["end"] >= start) and \
               (end is None or e["start"] <= end):
                ax.plot(e["t_peak"], e["peak"], "^", color="#5b8dd9", ms=6)
    if matches is not None:
        for _, m in matches[matches["status"] == "hit"].iterrows():
            if (start is None or m["t_peak_obs"] >= start) and \
               (end is None or m["t_peak_obs"] <= end):
                ax.plot([m["t_peak_obs"], m["t_peak_sim"]], [m["peak_obs"], m["peak_sim"]],
                        ":", color="#c94040", lw=1.2)
    ax.set_ylabel("discharge (m3/s)")
    ax.legend(loc="upper left", frameon=False)
    if title:
        ax.set_title(title)
    return ax
