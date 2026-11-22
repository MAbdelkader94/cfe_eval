#!/bin/bash
# smoke_test.sh - run the five steps on the first 5 gages, interactively, before
# submitting anything (a few minutes). Use a compute node:  qlogin -q IFC
#
#   bash jobs/smoke_test.sh
#
# Results go to <data root>/smoke_test/, not to the real results folder. The
# organized time series of the 5 gages are kept (step 1 skips them later).
set -e
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO}"
source jobs/env.sh
python scripts/01_organize.py --limit 5
export CFE_RESULTS="${CFE_DATA_ROOT}/smoke_test"
for s in 02_continuous 03_events 04_event_metrics; do python scripts/${s}.py --limit 5 --force; done
python scripts/05_merge.py --limit 5
python scripts/check_against_package.py
ls -lh "${CFE_RESULTS}/tables"
echo "smoke test passed; remove ${CFE_RESULTS} when you like"
