#!/usr/bin/env bash
# Stable public entrypoint. Feature implementations live in modules/.
set -Eeuo pipefail
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec bash "$base/modules/main.sh" "$@"
