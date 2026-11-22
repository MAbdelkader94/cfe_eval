#!/bin/bash
# 00_setup_env.sh - build the python environment once (login node, needs internet).
#
#   bash jobs/00_setup_env.sh
#
# Uses conda if it is on the PATH, otherwise python3 -m venv. If python3 on the
# login node is older than 3.10, load a newer one first (module avail python).
set -e
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CFE_DATA_ROOT="${CFE_DATA_ROOT:-$(cd "${REPO}/.." && pwd)}"
export CFE_ENV="${CFE_ENV:-${CFE_DATA_ROOT}/env}"

if [ -e "${CFE_ENV}" ]; then
    echo "environment already exists: ${CFE_ENV} (delete the folder to rebuild)"
elif command -v conda >/dev/null 2>&1; then
    # binary packages from conda-forge: the cluster compiler is too old to build numpy with pip
    conda create -y -p "${CFE_ENV}" -c conda-forge python=3.11 pip numpy pandas pyarrow numba matplotlib jupyterlab
    eval "$(conda shell.bash hook)" && conda activate "${CFE_ENV}"
    pip install --only-binary :all: hydrotools.events
else
    python3 -c 'import sys; assert sys.version_info >= (3, 10), "python >= 3.10 needed: " + sys.version'
    python3 -m venv "${CFE_ENV}"
    source "${CFE_ENV}/bin/activate"
    pip install --upgrade pip
    pip install -r "${REPO}/requirements.txt"
fi

source "${REPO}/jobs/env.sh"
python - <<'PY'
import numpy, pandas, pyarrow, matplotlib
from hydrotools.events.event_detection import decomposition  # noqa: F401
print("environment OK: python", __import__("sys").version.split()[0],
      "numpy", numpy.__version__, "pandas", pandas.__version__, "pyarrow", pyarrow.__version__)
PY
