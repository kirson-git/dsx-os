#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
source "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/common.sh"
source "$base/modules/log.sh"
exec python3 "$base/tools/clean_prereqs.py" "$@"
