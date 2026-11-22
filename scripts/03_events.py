"""
03_events.py - step 3: event separation, event matching and detection scores.

    python scripts/03_events.py                        (all gages, one process)
    python scripts/03_events.py --task 3 --ntasks 41   (one array task)

Method (team "Don't Runoff!" method as used for AGU 2026, functions in
cfe_eval/evaltools.py, settings in cfe_eval/config.py):
  1. hydrograph separation with NOAA-OWP hydrotools on the observed series and on
     each simulated series, same settings (halflife 6 h, 7-day rolling minimum
     baseflow, events shorter than 6 h dropped)
  2. events with a unit peak below 0.001 m3/s per km2 are dropped (baseflow noise);
     events that overlap a long MRMS gap are dropped for every series
  3. two event sets:
       all     every remaining event
       larger  events at or above the gage threshold = the k-th largest observed
               peak, k = round(3 per year x years in the window); the same
               threshold is applied to the simulated events of every product
  4. one-to-one matching: a simulated event is a candidate when it touches the
     window observed peak +/- 12 h, its peak is within 12 h and at least 5 % of
     the observed peak; cost = 0.7 min(|dt|/12, 2) + 0.3 |ln(Qsim/Qobs)|,
     lowest cost first, each event used once
  5. unmatched observed events are misses, unmatched simulated events are false
     alarms; POD = H/(H+M), FAR = FA/(H+FA), CSI = H/(H+M+FA)

Detection scores are given for the full window and by season, water year and
month. Hits and misses are counted in the period of the OBSERVED peak, false
alarms in the period of the SIMULATED peak.

Writes  results/parts/03_events/<site>.pkl with the tables
    events       one row per detected event of each series (obs, AORC, MRMS_P2, MRMS_RO)
    matches      one row per observed event, product and event set (hit or miss)
    false_alarms one row per unmatched simulated event
    contingency  hits, misses, false alarms, POD, FAR, CSI per product, set, period
    info         one row per gage: threshold, event counts
"""
import _path  # noqa: F401
import sys

import numpy as np
import pandas as pd

from cfe_eval import common as cm
from cfe_eval import config as cfg
from cfe_eval import evaltools as et

KW = dict(halflife=cfg.HALFLIFE, window=cfg.WINDOW, minimum_event_duration=cfg.MIN_EVENT_DURATION)
YEARS = (pd.Timestamp(cfg.END) - pd.Timestamp(cfg.START)).total_seconds() / (365.25 * 86400)


def overlaps_gap(ev: pd.DataFrame, gaps) -> np.ndarray:
    bad = np.zeros(len(ev), bool)
    for a, b in gaps:
        bad |= (ev["start"] <= b).to_numpy() & (ev["end"] >= a).to_numpy()
    return bad


def detect(series: pd.Series, area: float, gaps) -> tuple[pd.DataFrame, int, int]:
    """Events of one series after the unit-peak filter and the MRMS-gap rule.
    Returns (events with event_id 0..n-1, events before the gap rule, events removed)."""
    ev = et.filter_events(et.detect_events(series, **KW), area, cfg.MIN_UNIT_PEAK)
    n_all = len(ev)
    ev = ev[~overlaps_gap(ev, gaps)].reset_index(drop=True)
    ev.insert(0, "event_id", np.arange(len(ev)))
    return ev, n_all, n_all - len(ev)


def counts(matches: pd.DataFrame, fa: pd.DataFrame, by: str | None):
    """Hits and misses by period of the observed peak, false alarms by period of the simulated peak."""
    if by is None:
        return {"full": (int((matches["status"] == "hit").sum()), int((matches["status"] == "miss").sum()), len(fa))}
    keys = sorted(set(matches[by]) | set(fa[by]))
    return {k: (int(((matches["status"] == "hit") & (matches[by] == k)).sum()),
                int(((matches["status"] == "miss") & (matches[by] == k)).sum()),
                int((fa[by] == k).sum())) for k in keys}


def do_site(site: str) -> dict:
    g = cm.read_gages().set_index("site").loc[site]
    area = float(g["area_km2"])
    gaps = cm.read_gaps()
    df = cm.read_timeseries(site)
    obs = df["obs_scoring_cms"]
    if obs.notna().sum() < cfg.MIN_PAIRED_HOURS:
        raise RuntimeError("less than 30 days of paired data")

    # observed events and the larger-flood threshold of this gage
    ev_obs, n_obs_all, n_obs_gap = detect(obs, area, gaps)
    thr = np.nan
    if len(ev_obs):
        kth = max(1, int(round(cfg.LARGE_PER_YEAR * YEARS)))
        pk = np.sort(ev_obs["peak"].to_numpy())[::-1]
        thr = float(pk[min(kth, len(pk)) - 1])
    ev_obs["is_larger"] = ev_obs["peak"] >= thr if len(ev_obs) else False
    ev_obs.insert(0, "series", "obs")
    events = [ev_obs]
    info = {"gage": site, "area_km2": area, "event_threshold_cms": thr,
            "obs_events_detected": n_obs_all, "obs_events_in_mrms_gap": n_obs_gap,
            "obs_events_all": len(ev_obs), "obs_events_larger": int(ev_obs["is_larger"].sum())}

    matches_out, fa_out, cont_out = [], [], []
    for prod in cfg.PRODUCTS:
        ev_sim, _, _ = detect(df[prod].astype(float), area, gaps)
        ev_sim["is_larger"] = ev_sim["peak"] >= thr if len(ev_sim) and np.isfinite(thr) else False
        info[f"sim_events_all_{prod}"] = len(ev_sim)
        info[f"sim_events_larger_{prod}"] = int(ev_sim["is_larger"].sum())
        for eset in cfg.EVENT_SETS:
            o = ev_obs if eset == "all" else ev_obs[ev_obs["is_larger"]]
            s = ev_sim if eset == "all" else ev_sim[ev_sim["is_larger"]]
            o, s = o.reset_index(drop=True), s.reset_index(drop=True)
            if len(o):
                m = et.match_events(o, s, window_h=cfg.MATCH_WINDOW_H)
                hit = m["status"] == "hit"
                m["obs_event_id"] = o["event_id"].to_numpy()[m["obs_idx"].to_numpy()]
                m["sim_event_id"] = np.nan
                used = m.loc[hit, "sim_idx"].astype(int).to_numpy()
                m.loc[hit, "sim_event_id"] = s["event_id"].to_numpy()[used]
                m = m.drop(columns=["obs_idx", "sim_idx"])
            else:
                m = pd.DataFrame(columns=["t_peak_obs", "peak_obs", "status", "t_peak_sim", "peak_sim",
                                          "dt_h", "cost", "obs_event_id", "sim_event_id"])
                used = np.array([], int)
            fa = s.drop(index=used)[["event_id", "t_peak", "peak"]].rename(
                columns={"event_id": "sim_event_id", "t_peak": "t_peak_sim", "peak": "peak_sim"})
            m, fa = cm.add_time_labels(m, "t_peak_obs"), cm.add_time_labels(fa, "t_peak_sim")
            for ptype, by in [("full", None), ("season", "season"), ("water_year", "water_year"), ("month", "month")]:
                for period, (h, mi, f) in counts(m, fa, by).items():
                    cont_out.append({"gage": site, "product": prod, "event_set": eset, "period_type": ptype,
                                     "period": f"{period:02d}" if ptype == "month" else str(period),
                                     "obs_events": h + mi, "sim_events": h + f,
                                     "hits": h, "misses": mi, "false_alarms": f,
                                     "POD": h / (h + mi) if h + mi else np.nan,
                                     "FAR": f / (h + f) if h + f else np.nan,
                                     "CSI": h / (h + mi + f) if h + mi + f else np.nan})
            for x, store in [(m, matches_out), (fa, fa_out)]:
                x = x.copy()
                x.insert(0, "event_set", eset)
                x.insert(0, "product", prod)
                x.insert(0, "gage", site)
                store.append(x)
        ev_sim.insert(0, "series", prod)
        events.append(ev_sim)

    ev = pd.concat(events, ignore_index=True)
    ev["unit_peak_cms_km2"] = ev["peak"] / area
    ev = cm.add_time_labels(ev, "t_peak")
    ev.insert(0, "gage", site)
    return {"events": ev, "matches": pd.concat(matches_out, ignore_index=True),
            "false_alarms": pd.concat(fa_out, ignore_index=True),
            "contingency": pd.DataFrame(cont_out), "info": pd.DataFrame([info])}


if __name__ == "__main__":
    a = cm.task_args(__doc__.split("\n")[1])
    sys.exit(1 if cm.run_sites("03_events", a, do_site) else 0)
