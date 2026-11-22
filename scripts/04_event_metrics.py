"""
04_event_metrics.py - step 4: event-based evaluation of the matched events
(the hits of step 3): magnitude, timing and volume of each flood.

    python scripts/04_event_metrics.py                        (all gages, one process)
    python scripts/04_event_metrics.py --task 3 --ntasks 41   (one array task)

Needs the part files of step 3. For every matched pair (observed event, simulated
event) of each product and event set (cfe_eval/evaltools.py, event_metrics):
    peak_err_pct        (Qpeak_sim - Qpeak_obs) / Qpeak_obs * 100        magnitude
    peak_ratio          Qpeak_sim / Qpeak_obs                              magnitude, for log axes
    time_to_peak_err_h  t_peak_sim - t_peak_obs, negative = simulation early   peak timing
    rise_obs_h, rise_sim_h, rise_err_h   time from event start to peak, and sim - obs
    duration_err_h      event duration, sim - obs
    vol_err_pct         volume over the union of the two event windows
    vol_obs_mm, vol_sim_mm   the same volumes as runoff depth
    rbi_obs, rbi_sim    Richards-Baker flashiness on the union window
Each row carries the season, month and water year of the OBSERVED peak.

Writes  results/parts/04_event_metrics/<site>.pkl with the tables
    event_metrics       one row per matched event
    event_metrics_site  per gage, product, event set and period (full, season,
                        water_year): number of matched events, median and median
                        absolute value of the main errors
"""
import _path  # noqa: F401
import sys

import numpy as np
import pandas as pd

from cfe_eval import common as cm
from cfe_eval import config as cfg
from cfe_eval import evaltools as et

SUMMARY = ["peak_err_pct", "time_to_peak_err_h", "rise_err_h", "duration_err_h", "vol_err_pct"]


def site_summary(em: pd.DataFrame, keys: dict) -> list[dict]:
    rows = []
    groups = [("full", "full", em)]
    groups += [("season", str(k), x) for k, x in em.groupby("season")]
    groups += [("water_year", str(k), x) for k, x in em.groupby("water_year")]
    for ptype, period, x in groups:
        row = {**keys, "period_type": ptype, "period": period, "matched_events": len(x)}
        for c in SUMMARY:
            row[f"{c}_median"] = float(x[c].median())
            row[f"abs_{c}_median"] = float(x[c].abs().median())
        row["peak_ratio_median"] = float(x["peak_ratio"].median())
        rows.append(row)
    return rows


def do_site(site: str) -> dict:
    part = cm.load_part("03_events", site)
    if part.get("error"):
        raise RuntimeError("step 3 failed for this gage: " + part["error"].strip().splitlines()[-1])
    area = float(part["info"]["area_km2"].iloc[0])
    df = cm.read_timeseries(site)
    obs = df["obs_scoring_cms"]
    ev = part["events"].set_index(["series", "event_id"])
    out, summ = [], []
    for prod in cfg.PRODUCTS:
        sim = df[prod].astype(float)
        ev_sim = ev.loc[prod] if prod in ev.index.get_level_values(0) else pd.DataFrame()
        for eset in cfg.EVENT_SETS:
            m = part["matches"]
            m = m[(m["product"] == prod) & (m["event_set"] == eset) & (m["status"] == "hit")]
            if m.empty:
                continue
            m = m.rename(columns={"obs_event_id": "obs_idx", "sim_event_id": "sim_idx"})
            em = et.event_metrics(obs, sim, ev.loc["obs"], ev_sim, m, area)
            em.insert(0, "sim_event_id", m["sim_idx"].astype(int).to_numpy())
            em.insert(0, "obs_event_id", m["obs_idx"].astype(int).to_numpy())
            em["peak_ratio"] = em["peak_sim_cms"] / em["peak_obs_cms"]
            em["rise_err_h"] = em["rise_sim_h"] - em["rise_obs_h"]
            em["duration_err_h"] = em["duration_sim_h"] - em["duration_obs_h"]
            em["unit_peak_obs_cms_km2"] = em["peak_obs_cms"] / area
            em = cm.add_time_labels(em, "t_peak_obs")
            keys = {"gage": site, "product": prod, "event_set": eset}
            summ += site_summary(em, keys)
            for k in ["event_set", "product", "gage"]:
                em.insert(0, k, keys[k])
            out.append(em)
    return {"event_metrics": pd.concat(out, ignore_index=True) if out else pd.DataFrame(),
            "event_metrics_site": pd.DataFrame(summ)}


if __name__ == "__main__":
    a = cm.task_args(__doc__.split("\n")[1])
    sys.exit(1 if cm.run_sites("04_event_metrics", a, do_site) else 0)
