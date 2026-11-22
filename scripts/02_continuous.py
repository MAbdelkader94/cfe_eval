"""
02_continuous.py - step 2: long-term (whole series) evaluation of the hourly
simulated flow of each product against the observed flow.

    python scripts/02_continuous.py                        (all gages, one process)
    python scripts/02_continuous.py --task 3 --ntasks 41   (one array task)

Metrics (cfe_eval/evaltools.py, continuous_metrics), on hours with both values:
    NNSE   1 / (2 - NSE)                       0 to 1, 1 = perfect, 0.5 = as good as the mean
    NRMSE  RMSE / mean(observed) * 100         %   (the normalized RMSE)
    PB     sum(sim - obs) / sum(obs) * 100     %   percent bias, positive = too much flow
    also RMSE (m3/s), NSE, KGE, r, the number of hours and the two mean flows

Periods (column period_type / period), so the tables serve the seasonal and
climate-zone analysis directly:
    full         full          the scoring window, 2021-10-01 to 2025-12-31 UTC
    season       Winter ...    all hours of that season, every year pooled
    water_year   2022 ...      Oct to Sep
    season_year  2022-Winter   one season of one year (December counts for the next year)
    month        01 ... 12     all hours of that calendar month
A period with fewer than 30 days of paired hours is not scored.

Writes  results/parts/02_continuous/<site>.pkl   (merged by step 5)
"""
import _path  # noqa: F401
import sys

import numpy as np
import pandas as pd

from cfe_eval import common as cm
from cfe_eval import config as cfg
from cfe_eval import evaltools as et


def period_masks(index: pd.DatetimeIndex) -> list[tuple[str, str, np.ndarray]]:
    season, wy, month = cm.season_of(index), cm.water_year_of(index), index.month.to_numpy()
    syear = index.year.to_numpy() + (month == 12)          # December belongs to the next winter
    out = [("full", "full", np.ones(len(index), bool))]
    out += [("season", s, season == s) for s in cfg.SEASONS]
    out += [("water_year", str(y), wy == y) for y in np.unique(wy)]
    out += [("season_year", f"{y}-{s}", (syear == y) & (season == s))
            for y in np.unique(syear) for s in cfg.SEASONS]
    out += [("month", f"{m:02d}", month == m) for m in range(1, 13)]
    return out


def do_site(site: str) -> dict:
    df = cm.read_timeseries(site)
    obs = df["obs_scoring_cms"]
    masks = period_masks(df.index)
    rows = []
    for prod in cfg.PRODUCTS:
        sim = df[prod].astype(float)
        for ptype, period, m in masks:
            o, s = obs[m], sim[m]
            ok = (o.notna() & s.notna()).to_numpy()
            if ok.sum() < cfg.MIN_HOURS_PERIOD:
                continue
            met = et.continuous_metrics(o, s)
            rows.append({"gage": site, "product": prod, "period_type": ptype, "period": period,
                         "n_hours": met.pop("n"), "mean_obs_cms": float(o[ok].mean()),
                         "mean_sim_cms": float(s[ok].mean()), **met})
    if not any(r["period_type"] == "full" for r in rows):
        raise RuntimeError("less than 30 days of paired data")
    return {"continuous": pd.DataFrame(rows)}


if __name__ == "__main__":
    a = cm.task_args(__doc__.split("\n")[1])
    sys.exit(1 if cm.run_sites("02_continuous", a, do_site) else 0)
