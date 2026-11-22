# env.sh - sourced by every job and helper script. The one place to edit.
#
# REPO          this repository (set by the caller)
# CFE_DATA_ROOT folder with AGU26_QPE_CFE_results.zip; default = parent of the repository
# CFE_ENV       python environment made by jobs/00_setup_env.sh

export CFE_DATA_ROOT="${CFE_DATA_ROOT:-$(cd "${REPO}/.." && pwd)}"
export CFE_ENV="${CFE_ENV:-${CFE_DATA_ROOT}/env}"

# number of array tasks for steps 2 to 4 (818 gages / 41 tasks = about 20 gages per task)
export CFE_NTASKS="${CFE_NTASKS:-41}"

# one thread per task: the work is spread over tasks, not threads
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1

if [ -f "${CFE_ENV}/bin/activate" ]; then
    source "${CFE_ENV}/bin/activate"                       # venv
elif [ -d "${CFE_ENV}/conda-meta" ]; then
    eval "$(conda shell.bash hook 2>/dev/null)" && conda activate "${CFE_ENV}"   # conda prefix
else
    echo "ERROR: python environment not found at ${CFE_ENV}; run: bash jobs/00_setup_env.sh"
    exit 1
fi
