"""
06_qaqc_stats.py - quality statistics of every gage (zero flow, coverage, flat
lines, runoff depth, ...) for analysis/00_qaqc.ipynb. The notebook computes the
same table by itself; this script is for a kernel without pyarrow, or to
refresh the table from the command line. About one to two minutes.

    python scripts/06_qaqc_stats.py

Writes  results/tables/qaqc_stats.parquet and .csv
"""
import _path  # noqa: F401

from cfe_eval import qaqc

if __name__ == "__main__":
    qaqc.compute_stats(force=True)
