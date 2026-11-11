#!/usr/bin/env bash
# Shared module context; source without making cluster changes.
DPF_INSTALLER_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
base=$DPF_INSTALLER_DIR
export DPF_INSTALLER_DIR
