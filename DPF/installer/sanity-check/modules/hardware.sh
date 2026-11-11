#!/usr/bin/env bash
set -Eeuo pipefail
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
exec python3 "$base/tools/sanity.py" hardware "$@"
