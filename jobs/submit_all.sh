#!/bin/bash
# submit_all.sh - submit the whole evaluation to the IFC queue as a chain of jobs.
#
#   cd ~/Papers/cfe_evel/cfe_eval          (the repository root)
#   bash jobs/submit_all.sh                all five steps
#   bash jobs/submit_all.sh 2 5            only steps 2 and 5 (any list of steps)
#   EMAIL=you@uiowa.edu bash jobs/submit_all.sh     abort emails (-m a) to this address
#
# Chain:  1 organize -> 2 continuous (array) -+-> 5 merge
#                    -> 3 events (array) -> 4 event metrics (array) -+
# Each step waits for the steps it needs (-hold_jid). Every step is restart safe:
# finished gages are skipped, so submitting again only fills the gaps.
set -e
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO}"
source jobs/env.sh
STEPS="${*:-1 2 3 4 5}"
LOGS="${CFE_DATA_ROOT}/logs"
mkdir -p "${LOGS}"                       # must exist before qsub
N="${CFE_NTASKS}"
COMMON=(-o "${LOGS}" -v "CFE_DATA_ROOT=${CFE_DATA_ROOT},CFE_ENV=${CFE_ENV},CFE_NTASKS=${N}")
[ -n "${EMAIL}" ] && COMMON+=(-M "${EMAIL}")

has() { [[ " ${STEPS} " == *" $1 "* ]]; }
# a step is held only on the earlier steps submitted in this call
H1=""; has 1 && H1="-hold_jid cfe_01_organize"
H4="${H1}"; has 3 && H4="-hold_jid cfe_03_events"
H5=""; for s in "2:cfe_02_continuous" "3:cfe_03_events" "4:cfe_04_event_metrics" "1:cfe_01_organize"; do
    has "${s%%:*}" && H5="${H5:+$H5,}${s##*:}"; done; [ -n "${H5}" ] && H5="-hold_jid ${H5}"

echo "data root: ${CFE_DATA_ROOT}"
echo "logs:      ${LOGS}"
echo "steps:     ${STEPS}   array tasks: ${N}"
has 1 && qsub "${COMMON[@]}" jobs/01_organize.job
has 2 && qsub "${COMMON[@]}" ${H1} -t 1-${N} -tc ${N} jobs/02_continuous.job
has 3 && qsub "${COMMON[@]}" ${H1} -t 1-${N} -tc ${N} jobs/03_events.job
has 4 && qsub "${COMMON[@]}" ${H4} -t 1-${N} -tc ${N} jobs/04_event_metrics.job
has 5 && qsub "${COMMON[@]}" ${H5} jobs/05_merge.job
echo "monitor:  qstat -u \$USER      closeout:  bash jobs/closeout.sh"
