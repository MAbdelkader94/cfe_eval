"""
config.py - every path and setting of the evaluation in one place.

Paths
    The data root is the folder that holds AGU26_QPE_CFE_results.zip. By default
    it is the parent folder of this repository, so on Argon the layout is

        ~/Papers/cfe_evel/                      <- data root
            AGU26_QPE_CFE_results.zip
            cfe_eval/                           <- this repository
            organized/                          <- written by step 1
            results/                            <- written by steps 2 to 5

    Set the environment variable CFE_DATA_ROOT to use another folder.

Settings
    The event settings are the ones of the AGU 2026 evaluation (config.py and
    eval_all.py in 05_scripts.zip of the results package). Change them here and
    every step follows.
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("CFE_DATA_ROOT", REPO.parent)).resolve()

PACKAGE_ZIP = DATA_ROOT / "AGU26_QPE_CFE_results.zip"
ORGANIZED = DATA_ROOT / "organized"
RESULTS = Path(os.environ.get("CFE_RESULTS", DATA_ROOT / "results")).resolve()
PARTS = RESULTS / "parts"            # one file per gage and step (restart safe)
TABLES = RESULTS / "tables"          # final merged tables
FIGURES = RESULTS / "figures"        # first version of the figures (notebooks/)
REPORT = RESULTS / "report"          # figures and tables of the analysis notebooks, one folder per analysis
CLIMATE_CSV = REPO / "static" / "gage_climate.csv"

# product key -> folder name inside the results package
PRODUCTS = {"AORC": "01_AORC", "MRMS_P2": "02_MRMS_Pass2", "MRMS_RO": "03_MRMS_RadarOnly"}
PRODUCT_LABEL = {"AORC": "AORC", "MRMS_P2": "MRMS Pass 2", "MRMS_RO": "MRMS radar-only"}

# scoring window (UTC). The runs start on 2020-10-15; the first year is warm-up.
START = "2021-10-01 00:00"
END = "2025-12-31 00:00"

# seasons by calendar month of the UTC time stamp
SEASON_OF_MONTH = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
                   6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall", 10: "Fall", 11: "Fall"}
SEASONS = ["Fall", "Winter", "Spring", "Summer"]                 # order used in the figures
ZONES = ["Arid", "Semi-arid", "Semi-humid", "Humid"]             # order used in the figures

# drainage area classes (km2)
AREA_BINS = [0, 100, 500, 1000]
AREA_LABELS = ["<100", "100-500", "500-1000"]

# hydrograph separation (NOAA-OWP hydrotools), same for observed and simulated flow
HALFLIFE = "6h"               # smoothing halflife
WINDOW = "7D"                 # rolling minimum window for the baseflow
MIN_EVENT_DURATION = "6h"     # shorter events are dropped
MIN_UNIT_PEAK = 0.001         # m3/s per km2; smaller events are baseflow noise

# larger floods: observed peak exceeded about this many times per year at a gage
LARGE_PER_YEAR = 3.0
EVENT_SETS = ["all", "larger"]

# event matching
MATCH_WINDOW_H = 12.0         # +/- hours around the observed peak
MIN_PAIRED_HOURS = 24 * 30    # a gage needs at least 30 days of paired data
MIN_HOURS_PERIOD = 24 * 30    # a season or water year needs this many hours to be scored
