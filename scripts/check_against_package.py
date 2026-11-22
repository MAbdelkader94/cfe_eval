"""
check_against_package.py - compare the merged tables with the evaluation tables
shipped inside AGU26_QPE_CFE_results.zip (organized/package_eval). The method
and settings are the same, so the numbers should agree up to the rounding of
the flows in the package CSV files (6 digits).

    python scripts/check_against_package.py

Prints, per product and event set, the number of gages compared, how many have
identical hits / misses / false alarms, and the largest difference of the
whole-series scores and of the per-event errors.
"""
import _path  # noqa: F401
import numpy as np
import pandas as pd

from cfe_eval import common as cm
from cfe_eval import config as cfg

SETS = {"all": "eval_all_events", "larger": "eval_larger_events"}


def main():
    cont = cm.read_table("continuous_metrics")
    cont = cont[cont["period_type"] == "full"].set_index(["gage", "product"])
    ctg = cm.read_table("contingency")
    ctg = ctg[ctg["period_type"] == "full"]
    em = cm.read_table("event_metrics")
    cases = same_cases = 0
    for eset, folder in SETS.items():
        for prod in cfg.PRODUCTS:
            ref = pd.read_csv(cfg.ORGANIZED / "package_eval" / folder / f"site_summary_{prod}.csv",
                              dtype={"gage": str}).set_index("gage")
            new = ctg[(ctg["event_set"] == eset) & (ctg["product"] == prod)].set_index("gage")
            common = ref.index.intersection(new.index)
            same = np.ones(len(common), bool)
            for c in ["hits", "misses", "false_alarms"]:
                same &= (ref.loc[common, c].to_numpy() == new.loc[common, c].to_numpy())
            line = f"{eset:6s} {prod:8s} gages {len(common):4d}  identical hits/misses/false alarms {same.sum():4d}"
            c2 = cont.xs(prod, level="product").reindex(common)
            for c in ["PBIAS_pct", "NNSE", "NRMSE_pct"]:
                d = np.nanmax(np.abs(c2[c].to_numpy() - ref.loc[common, c].to_numpy()))
                line += f"  max|d {c}| {d:.2g}"
            refe = pd.read_csv(cfg.ORGANIZED / "package_eval" / folder / f"events_{prod}.csv", dtype={"gage": str})
            refe = refe[refe["gage"].isin(common)]
            refe["t_peak_obs"] = pd.to_datetime(refe["t_peak_obs"], utc=True)
            newe = em[(em["event_set"] == eset) & (em["product"] == prod) & em["gage"].isin(common)]
            j = refe.merge(newe, on=["gage", "t_peak_obs"], suffixes=("_ref", "_new"))
            line += f"  matched events {len(newe)} vs {len(refe)} in package"
            for c in ["peak_err_pct", "time_to_peak_err_h", "vol_err_pct"]:
                d = np.nanmax(np.abs(j[c + "_ref"] - j[c + "_new"])) if len(j) else np.nan
                line += f"  max|d {c}| {d:.2g}"
            print(line)
            cases += len(common)
            same_cases += int(same.sum())
    print(f"RESULT: identical hits, misses and false alarms in {same_cases} of {cases} "
          f"gage x product x event set cases ({100 * same_cases / max(cases, 1):.1f} %)")
    print("Small differences are expected: the flows in the package CSV files are rounded to 6 digits,\n"
          "the package tables were computed from the unrounded model output. An event close to a\n"
          "threshold can then fall on the other side.")


if __name__ == "__main__":
    main()
