#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${CUBEON_PYTHON:-}"
if [[ -z "$python_bin" ]]; then
  for candidate in "$root/.venv/bin/python" "$root/.venv-build/bin/python"; do
    if [[ -x "$candidate" ]]; then python_bin="$candidate"; break; fi
  done
fi
python_bin="${python_bin:-python3}"
command=sync
if [[ "${1:-}" == setup ]]; then command=setup; shift; fi
exec "$python_bin" "$root/worker/manage-cosmetics.py" "$command" "$@"
