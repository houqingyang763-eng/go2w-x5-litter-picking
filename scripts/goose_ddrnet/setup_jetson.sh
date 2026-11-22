#!/usr/bin/env bash
set -euo pipefail
umask 077

user_home="$HOME"
code="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
workspace="$(dirname -- "$code")"
if [[ "$code" != "$user_home/hqy/goose_ddrnet/code" || "$(uname -m)" != aarch64 ]]; then
    printf '%s\n' 'Run this on Jetson from $HOME/hqy/goose_ddrnet/code.' >&2
    exit 2
fi
for directory in "$workspace/wheelhouse" "$workspace/cache" "$workspace/tmp"; do
    [[ ! -L "$directory" ]]
    mkdir -p -- "$directory"
done

venv="$workspace/.venv"
[[ ! -L "$venv" ]]
if [[ ! -x "$venv/bin/python" ]]; then
    /usr/bin/python3 -I -m venv --without-pip "$venv"
fi
python="$venv/bin/python"
"$python" -I -B -c 'import sys; from pathlib import Path; assert sys.version_info[:2] == (3, 8); assert Path(sys.prefix) == Path(sys.argv[1]) and sys.base_prefix != sys.prefix' "$venv"
grep -Fxq 'include-system-site-packages = false' "$venv/pyvenv.cfg"

unset PYTHONPATH PYTHONHOME
export HOME="$workspace" XDG_CACHE_HOME="$workspace/cache" TMPDIR="$workspace/tmp"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PIP_CONFIG_FILE=/dev/null CUDA_CACHE_DISABLE=1
wheelhouse="$workspace/wheelhouse"
requirements="$code/requirements-jetson.txt"
pip_wheel="$wheelhouse/pip-24.3.1-py3-none-any.whl"
pip_line="$(grep '^pip==24\.3\.1 --hash=sha256:' "$requirements")"
printf '%s  %s\n' "${pip_line##*:}" "$pip_wheel" | sha256sum --check --status

PYTHONPATH="$pip_wheel" "$python" -s -B -m pip --isolated --disable-pip-version-check install \
    --no-index --find-links "$wheelhouse" --require-hashes --no-cache-dir --no-compile -r "$requirements"
"$python" -I -B -m pip --isolated --disable-pip-version-check check
"$python" -I -B - <<'PYTHON'
import torch

if not torch.cuda.is_available():
    raise SystemExit("CUDA is unavailable in the project environment.")
x = torch.arange(4, device="cuda")
assert (x + x).tolist() == [0, 2, 4, 6]
print("PyTorch", torch.__version__, "CUDA", torch.version.cuda, "GPU", torch.cuda.get_device_name(0))
PYTHON
