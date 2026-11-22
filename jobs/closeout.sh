#!/bin/bash
# closeout.sh - the checks to run after the jobs finish and before any analysis.
#
#   bash jobs/closeout.sh
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO}"
source jobs/env.sh
LOGS="${CFE_DATA_ROOT}/logs"; RES="${CFE_RESULTS:-${CFE_DATA_ROOT}/results}"
echo "jobs still in the queue:        $(qstat -u "$USER" 2>/dev/null | grep -c ' cfe_')"
echo "log files:                      $(ls "${LOGS}" 2>/dev/null | grep -c '^cfe_')"
echo "logs without 'Exit code: 0':    $(grep -L 'Exit code: 0' "${LOGS}"/cfe_* 2>/dev/null | wc -l)   (expected 0)"
grep -L 'Exit code: 0' "${LOGS}"/cfe_* 2>/dev/null | head -20
echo "organized time series:          $(ls "${CFE_DATA_ROOT}/organized/timeseries" 2>/dev/null | wc -l)   (expected 818)"
for s in 02_continuous 03_events 04_event_metrics; do
    echo "part files ${s}:   $(ls "${RES}/parts/${s}" 2>/dev/null | grep -c '\.pkl$')   (expected 818)"
done
echo "final tables:"; ls -lh "${RES}/tables" 2>/dev/null
[ -f "${RES}/tables/run_log.parquet" ] && python scripts/check_against_package.py
