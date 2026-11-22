# cfe_eval

Evaluation of CFE streamflow (NextGen, uncalibrated, hourly) forced with three rain
products, against USGS observations at 818 gages:

| Key | Product |
|---|---|
| `AORC` | AORC hourly analysis |
| `MRMS_P2` | MRMS MultiSensor QPE Pass 2 (radar + gauge corrected) |
| `MRMS_RO` | MRMS radar-only QPE |

The input is the package `AGU26_QPE_CFE_results.zip` (team "Don't Runoff!", Summer
Institute 2026). The method is the team method used for AGU 2026 (`evaltools.py` in the
package, copied here unchanged). What this repository adds: an organized data store, the
same scores split by season, water year and month, a climate (aridity) zone for every
gage, and job scripts for the IFC queue on Argon.

## The five steps

| Step | Script | What it does |
|---|---|---|
| 1 | `scripts/01_organize.py` | checks the package and writes one hourly file per gage plus the gage table |
| 2 | `scripts/02_continuous.py` | long-term series metrics: NNSE, NRMSE, PB (also RMSE, NSE, KGE, r) |
| 3 | `scripts/03_events.py` | event separation, event matching, POD, FAR, CSI |
| 4 | `scripts/04_event_metrics.py` | event-based evaluation of the matched events: peak magnitude, peak timing, time to peak, volume |
| 5 | `scripts/05_merge.py` | merges the per-gage results into the final tables |

Steps 2 to 4 work gage by gage and write one part file per gage, so they run as array
jobs and can be restarted at any time: finished gages are skipped.

## Folder layout

The data never go into the repository. They sit next to it:

```
cfe_evel/                            data root (the parent folder of the repository)
  AGU26_QPE_CFE_results.zip          input
  cfe_eval/                          this repository
  env/                               python environment      (jobs/00_setup_env.sh)
  organized/                         step 1
    gages.csv
    timeseries/<site>.parquet
    mrms_long_gaps.csv
    package_eval/  package_docs/  manifest.json
  results/
    parts/<step>/<site>.pkl          steps 2 to 4, one file per gage
    tables/                          step 5, the tables to analyse
    figures/                         notebook figures
  logs/                              job logs
```

Another data root: `export CFE_DATA_ROOT=/path/to/folder` before any command.

## Run on Argon (IFC queue)

Follow `Argon_IFC_job_submission_guide.md` for the general checks. From an Argon login
node (not from IDAS; IDAS only shows the same files):

```bash
cd ~/Papers/cfe_evel
git clone https://github.com/MAbdelkader94/cfe_eval.git
cd cfe_eval

bash jobs/00_setup_env.sh          # once: python environment in ../env
qlogin -q IFC                      # smoke test on a compute node, 5 gages, a few minutes
bash jobs/smoke_test.sh
exit

qstat -g c | grep IFC              # free slots; the arrays use 41 slots each
bash jobs/submit_all.sh            # all five steps, chained with -hold_jid
qstat -u $USER
bash jobs/closeout.sh              # after the jobs: failed tasks, counts, check against the package
```

Expected run time: step 1 about 10 minutes; steps 2 to 4 a few minutes per array task
(about 3 s per gage for the event separation); step 5 about a minute.

Useful variants:

```bash
bash jobs/submit_all.sh 3 4 5                      # only some steps
EMAIL=you@uiowa.edu bash jobs/submit_all.sh        # abort emails to this address
CFE_NTASKS=82 bash jobs/submit_all.sh              # more, smaller array tasks
qsub -o "$PWD/../logs" -t 7-7 jobs/03_events.job   # rerun one array task
```

`jobs/env.sh` is the only file to edit if the environment or the paths differ.

Without a scheduler (laptop, IDAS) the same steps run in one process:

```bash
python scripts/01_organize.py
python scripts/02_continuous.py
python scripts/03_events.py
python scripts/04_event_metrics.py
python scripts/05_merge.py
python scripts/check_against_package.py
```

## Method in short

All settings are in `cfe_eval/config.py`.

- Scoring window: 2021-10-01 00:00 to 2025-12-31 00:00 UTC. The first year of the runs is warm-up.
- Observed flow: `obs_scoring_cms` of the package (hourly mean of the hour ending at T, gaps up to 24 h interpolated).
- Seasons by UTC month: Winter Dec to Feb, Spring Mar to May, Summer Jun to Aug, Fall Sep to Nov.
- Long-term metrics on the hours with both values: NNSE = 1 / (2 - NSE); NRMSE = RMSE / mean(observed) x 100; PB = sum(sim - obs) / sum(obs) x 100. A period needs at least 30 days of paired hours.
- Event separation: NOAA-OWP hydrotools (halflife 6 h, 7-day rolling minimum baseflow, minimum duration 6 h), the same on observed and simulated flow. Events with a unit peak below 0.001 m3/s per km2 are dropped. Events overlapping a long MRMS gap are dropped for every series.
- Two event sets: `all`, and `larger` = events at or above the 13th-largest observed peak of the gage (about 3 per year), the same threshold for the simulated events of every product.
- Matching: one to one, simulated peak within +/- 12 h of the observed peak and at least 5 % of it, cost = 0.7 min(|dt| / 12, 2) + 0.3 |ln(Qsim / Qobs)|.
- Detection: POD = H / (H + M), FAR = FA / (H + FA), CSI = H / (H + M + FA). By season, hits and misses count in the season of the observed peak, false alarms in the season of the simulated peak.
- Matched events: peak error (%), peak ratio, peak timing error (h, negative = early), time to peak from the event start (rise time) and its error, duration error, volume error (%) over the union of the two event windows, Richards-Baker flashiness.

## Tables (results/tables, parquet and csv)

Every table carries `aridity_zone`, `area_km2`, `area_class` and `state_tag`, so a figure
by climate type, basin size or state is one `groupby` away.

| Table | One row per | Main columns |
|---|---|---|
| `qaqc_stats`, `qaqc_sites.csv` | gage | quality statistics; rule flags, `keep`, `drop_reasons` (written by `analysis/00_qaqc.ipynb`) |
| `gages` | gage | location, area, radar distance, aridity zone, event threshold, event counts |
| `continuous_metrics` | gage, product, period | `period_type` (full, season, water_year, season_year, month), `period`, `n_hours`, RMSE, NRMSE_pct, PBIAS_pct, NSE, NNSE, KGE, r |
| `events_detected` | detected event | `series` (obs or product), start, end, t_peak, peak, rise_h, duration_h, volume_m3, is_larger, season, water_year |
| `event_matches` | observed event, product, event set | status (hit or miss), matched simulated peak, dt_h, cost, season |
| `false_alarms` | unmatched simulated event, product, event set | t_peak_sim, peak_sim, season |
| `contingency` | gage, product, event set, period | hits, misses, false_alarms, POD, FAR, CSI |
| `event_metrics` | matched event, product, event set | peak_err_pct, peak_ratio, time_to_peak_err_h, rise_obs_h, rise_sim_h, rise_err_h, vol_err_pct, season |
| `event_metrics_site` | gage, product, event set, period | number of matched events, median and median absolute errors |
| `run_log` | gage, step | ok, error or missing |

## Climate zones

`static/gage_climate.csv` gives each gage its aridity zone (Arid, Semi-arid, Semi-humid,
Humid) from the polygons in `Aridity_zones.rar` (`AZ.shp`). The zone is the one that
contains the gage location; 5 coastal gages outside every polygon take the nearest one.
The 818 gages: Humid 717, Semi-humid 44, Semi-arid 35, Arid 22. To rebuild the file:

```bash
python scripts/00_assign_climate.py --gages gages.csv --zones Aridity_zones/AZ.shp
```

## Analysis notebooks

The folder `analysis/` holds one notebook per analysis. They read `results/tables` and
need only numpy, pandas and matplotlib (plus pyarrow for the first run of notebook 00).
Run them in this order:

| Notebook | Content | Writes |
|---|---|---|
| `00_qaqc.ipynb` | zero flow and other checks of the CFE runs, checks of the USGS record, screening rules, list of gages to keep | `results/tables/qaqc_stats`, `results/tables/qaqc_sites.csv` |
| `01_long_term.ipynb` | NNSE, KGE, PB, NRMSE: tables, box plots by climate type and season, maps, differences between rain products, water years, basin size | figures |
| `02_events.ipynb` | POD, FAR, CSI, performance diagram, matched-event errors (peak, timing, time to peak, volume), maps | figures |

Paths need no editing: each notebook finds the repository from the folder it is opened in
and takes the data from the folder next to the repository, so it runs the same from IDAS
(`~/hpchome/Papers/cfe_evel/cfe_eval/analysis`) and from Argon. Figures go to
`results/figures/<notebook name>/` as PNG at 300 dpi, with the tables behind them as CSV.

Notebooks 01 and 02 use only the gages kept by notebook 00 (`USE_QAQC = True`) and stop
with a message if notebook 00 has not been run. By default every screening rule removes its
flagged gages; the switches are in section 5 of notebook 00.

Notebook 00 reads the 818 hourly files on its first run. If the IDAS kernel has no
pyarrow, build that table once on Argon instead:

```bash
REPO=$PWD; source jobs/env.sh
python scripts/06_qaqc_stats.py
```

Maps use the Albers Equal Area projection for the conterminous United States (EPSG:5070)
with the aridity zones in the background. The base map (`static/basemap_albers.json`) is
already projected and the projection of the gages is written in numpy
(`cfe_eval/maps.py`), so no GIS library is needed. `scripts/00_build_basemap.py` rebuilds
the base map from `AZ.shp` and the Natural Earth state borders.

The repository stores the notebooks without their outputs. After running them, `git pull`
may refuse to update a notebook you changed; `git stash` before the pull (and `git stash
pop` after it) keeps your version.

`notebooks/01_seasonal_climate_boxplots.ipynb` is the first version of the seasonal
figures; `analysis/` replaces it.

## Check

`scripts/check_against_package.py` compares the full-window results with the evaluation
tables inside the package. They agree up to the rounding of the package CSV files (flows
are stored with 6 digits; an event close to a threshold can change side).
