#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
source "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/common.sh"
exec python3 "$base/tools/discover_dpus.py" "$@"
