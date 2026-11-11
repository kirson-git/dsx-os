#!/usr/bin/env bash
# DPF checks and installer. The implementation lives in installer/.
#   ./dpf-install.sh --help
#   ./dpf-install.sh --sanity --prereq
set -Eeuo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec bash "$here/installer/dpf-install.sh" "$@"
