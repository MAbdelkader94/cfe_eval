"""
05_merge.py - step 5: put the per-gage part files of steps 2 to 4 together.

    python scripts/05_merge.py                    (stops if a gage is missing or failed)
    python scripts/05_merge.py --allow-missing    (merge what is there)
    python scripts/05_merge.py --limit 5          (after a smoke test)

Writes  results/tables/  (each table as .parquet and .csv; every table has the
        gage attributes aridity_zone, area_km2, area_class, state_tag)
    gages                gage attributes + event threshold and event counts (step 3)
    continuous_metrics   step 2: gage x product x period
    events_detected      step 3: every detected event of every series
    event_matches        step 3: every observed event, hit or miss, per product and set
    false_alarms         step 3: unmatched simulated events
    contingency          step 3: POD, FAR, CSI per gage x product x set x period
    event_metrics        step 4: one row per matched event
    event_metrics_site   step 4: medians per gage x product x set x period
    run_log              status of every gage in every step
"""
import _path  # noqa: F401
import argparse
import sys

import pandas as pd

from cfe_eval import common as cm

STEPS = {"02_continuous": ["continuous"],
         "03_events": ["events", "matches", "false_alarms", "contingency", "info"],
         "04_event_metrics": ["event_metrics", "event_metrics_site"]}
NAMES = {"continuous": "continuous_metrics", "events": "events_detected", "matches": "event_matches"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-missing", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    gages = cm.read_gages()
    sites = gages["site"].tolist()[: a.limit or None]
    log, bucket = [], {t: [] for ts in STEPS.values() for t in ts}
    for step, tables in STEPS.items():
        for site in sites:
            if not cm.part_path(step, site).exists():
                log.append({"gage": site, "step": step, "status": "missing", "note": ""})
                continue
            part = cm.load_part(step, site)
            if part.get("error"):
                log.append({"gage": site, "step": step, "status": "error",
                            "note": part["error"].strip().splitlines()[-1][:200]})
                continue
            log.append({"gage": site, "step": step, "status": "ok", "note": ""})
            for t in tables:
                if len(part[t]):
                    bucket[t].append(part[t])
    log = pd.DataFrame(log)
    print(log.groupby(["step", "status"]).size().to_string(), flush=True)
    bad = log[log["status"] != "ok"]
    if len(bad):
        print(bad.to_string(index=False), flush=True)
        if not a.allow_missing:
            sys.exit("ERROR: gages missing or failed (list above). Rerun those tasks, "
                     "or merge anyway with --allow-missing")

    print("tables:", flush=True)
    info = pd.concat(bucket.pop("info"), ignore_index=True) if bucket["info"] else pd.DataFrame(columns=["gage"])
    g = gages.merge(info.drop(columns=["area_km2"], errors="ignore").rename(columns={"gage": "site"}),
                    on="site", how="left")
    cm.write_table(g, "gages")
    for t, parts in bucket.items():
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        cm.write_table(cm.with_attrs(df, gages), NAMES.get(t, t))
    cm.write_table(log, "run_log")
    print(f"merged {len(sites)} gages -> {cm.cfg.TABLES}", flush=True)


if __name__ == "__main__":
    main()
