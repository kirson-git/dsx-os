#!/usr/bin/env bash
# Guided entrypoint, called by dpf-install.sh after argument validation.
set -euo pipefail
source "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/common.sh"
context=${1:-}
storage=${2:-local-path}
seconds=${3:-600}
if [[ -z "$context" ]]; then context=$(kubectl config current-context); fi
common=(--context "$context" --storage-class "$storage" --timeout "$seconds")
last_action=status
while true; do
    python3 "$base/tools/ui.py" menu "$context"
    printf '\nChoose [1]: '
    if ! IFS= read -r choice; then printf '\n'; exit 0; fi
    result=0
    case ${choice:-1} in
        [Ss])
            printf '\n  1  Prerequisites\n  2  Control-plane hardware\n  3  Storage read/write (temporary PVC and pod)\n  0  Back\n\nChoose [1]: '
            if ! IFS= read -r check; then exit 0; fi
            case ${check:-1} in
                1) mode=--prereq ;;
                2) mode=--hardware ;;
                3) mode=--storage ;;
                0) continue ;;
                *) echo 'Choose 0-3.'; continue ;;
            esac
            bash "$base/dpf-install.sh" --sanity "$mode" --context "$context" --storage-class "$storage" || result=$? ;;
        [Ll]) python3 "$base/tools/install_log.py" show || result=$? ;;
        [Mm])
            if [[ "$last_action" == clean ]]; then
                bash "$base/dpf-install.sh" --clean --more "${common[@]}" || result=$?
            else
                bash "$base/dpf-install.sh" --diagnose --more "${common[@]}" || result=$?
            fi ;;
        1) bash "$base/dpf-install.sh" --status "${common[@]}" || result=$? ;;
        2) bash "$base/dpf-install.sh" --install-prereq --dry-run "${common[@]}" || result=$? ;;
        3) bash "$base/dpf-install.sh" --install-prereq "${common[@]}" || result=$? ;;
        4) bash "$base/commands/discover-nics.sh" --context "$context" || result=$? ;;
        5)
            printf '\nSettings are collected for the later DPF installation.\nThe prerequisite installer uses the context and storage shown above.\n'
            bash "$base/helper.sh" configure || result=$? ;;
        6) bash "$base/dpf-install.sh" --diagnose "${common[@]}" || result=$? ;;
        7)
            printf '\nGuide: %s/lab/README.md\n' "$base"
            printf 'YAML:  %s/lab/zero-trust/ and lab/passthrough/\n' "$base" ;;
        8)
            last_action=clean
            if bash "$base/dpf-install.sh" --clean "${common[@]}"; then
                storage_flags=()
                confirmation=CLEAN
                printf '\nAlso delete lab PVCs and bound PVs? [y/N]: '
                if ! IFS= read -r answer; then exit 0; fi
                case "$answer" in
                    [Yy]|[Yy][Ee][Ss])
                        storage_flags=(--delete-storage)
                        confirmation='CLEAN STORAGE'
                        if ! bash "$base/dpf-install.sh" --clean --delete-storage "${common[@]}"; then continue; fi ;;
                    ''|[Nn]|[Nn][Oo]) ;;
                    *) echo 'Cancelled. Choose y or n.'; continue ;;
                esac
                printf '\nType %s to execute this reset, or Enter to cancel: ' "$confirmation"
                if ! IFS= read -r answer; then exit 0; fi
                if [[ "$answer" == "$confirmation" ]]; then
                    bash "$base/dpf-install.sh" --clean --yes "${storage_flags[@]}" "${common[@]}" || result=$?
                else
                    echo 'Cancelled. No changes.'
                fi
            else
                result=$?
            fi ;;
        9) bash "$base/dpf-install.sh" --install-dpf "${common[@]}" || result=$? ;;
        10) bash "$base/dpf-install.sh" --check-bmc "${common[@]}" || result=$? ;;
        0) exit 0 ;;
        *) echo 'Choose 0-10, S, M or L.' ;;
    esac
    if [[ ${choice:-1} != 8 && ${choice:-1} != [Mm] ]]; then last_action=status; fi
done
