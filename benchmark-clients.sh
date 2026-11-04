#!/usr/bin/env bash
set -euo pipefail
task_repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$task_repo_dir/.venv-build/bin/python" -u "$task_repo_dir/tools/benchmark_clients.py" "$@"
