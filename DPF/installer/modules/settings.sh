#!/usr/bin/env bash
# Preparation only: settings, read-only checks, optional temporary NIC probes.
set -euo pipefail
umask 077
source "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/common.sh"

usage() {
    cat <<'EOF'
DPF v26.4.0 — preparation helper (no installation)
Usage: bash helper.sh [menu|configure [FILE]|validate FILE|check [FILE]|discover-nics [FILE]|--help]
  menu       Interactive menu (default).
  configure  Ask questions; save JSON settings (default: state/answers.json).
             Refuses to overwrite an existing file. No passwords are collected.
  validate   Validate a JSON settings file offline; no cluster access.
  check      Read cluster inventory with the saved context, or the current context
             if FILE is omitted. Save a new report under state/check-*/.
  discover-nics  Inspect Linux-node interfaces using temporary hostNetwork pods
                in default, then delete them. FILE selects the saved context;
                otherwise use current context. Reports: state/nics-*/.
Exit codes: 0 successful action/inventory without detected failures; 1 failure;
            2 invalid command usage. A successful check is not install approval.
Requires: Bash, Python 3; configure needs jq; check needs kubectl, helm and timeout.
NIC discovery needs kubectl, timeout and permission to create/read/delete pods.
EOF
}

need() { command -v "$1" >/dev/null || { printf 'Missing tool: %s\n' "$1" >&2; exit 1; }; }
ask() {
    local variable=$1 label=$2 default=${3:-} answer
    printf '%s%s: ' "$label" "${default:+ [$default]}" >&2
    if ! IFS= read -r answer; then
        printf '\nInput ended; no settings saved.\n' >&2
        exit 1
    fi
    printf -v "$variable" '%s' "${answer:-$default}"
}

configure() {
    need jq
    local target=${1:-$base/state/answers.json}
    [[ ! -e "$target" && ! -L "$target" ]] || { echo 'Settings file exists; choose a new filename.' >&2; return 1; }
    local context node_interface management_cidr bmc_ips bmc_user dpu_api_vip vip_mode dhcp storage_class registry payload
    echo 'Standalone DPF / Zero Trust. Enter settings for the target cluster.'
    echo 'The interface is on the Kubernetes nodes, not necessarily this admin machine.'
    echo 'To list node NICs first, use the discover-nics command or menu option 5.'
    ask context 'Kubernetes context (kubectl config get-contexts lists names)'
    ask node_interface 'Kubernetes node OOB interface'
    ask management_cidr 'Management IPv4 CIDR'
    ask bmc_ips 'DPU BMC IPv4 addresses, comma separated'
    ask bmc_user 'DPU BMC username' root
    ask dpu_api_vip 'Reserved DPU Kubernetes API VIP (IPv4)'
    ask vip_mode 'VIP delivery: keepalived (NVIDIA example), existing, metallb-l2, metallb-bgp, undecided' keepalived
    ask dhcp 'Management DHCP: external, temporary, missing' external
    ask storage_class 'Existing StorageClass for Kamaji etcd' local-path
    ask registry 'Image source: upstream or Harbor hostname/project' upstream
    payload=$(jq -n --arg context "$context" --arg node_interface "$node_interface" \
        --arg management_cidr "$management_cidr" --arg bmc_ips "$bmc_ips" \
        --arg bmc_user "$bmc_user" --arg dpu_api_vip "$dpu_api_vip" \
        --arg vip_mode "$vip_mode" --arg dhcp "$dhcp" \
        --arg storage_class "$storage_class" --arg registry "$registry" \
        '{schema_version:1,dpf_version:"v26.4.0",mode:"zero-trust",context:$context,
          node_interface:$node_interface,management_cidr:$management_cidr,
          bmc_ips:($bmc_ips|split(",")|map(gsub("^\\s+|\\s+$";""))),bmc_user:$bmc_user,
          dpu_api_vip:$dpu_api_vip,vip_mode:$vip_mode,dhcp:$dhcp,
          storage_class:$storage_class,registry:$registry}')
    printf '%s\n' "$payload" | python3 "$base/tools/lib.py" save "$target"
}

need python3
case ${1:-menu} in
    --help|-h) usage ;;
    configure) [[ $# -le 2 ]] || { usage; exit 2; }; configure "${2:-}" ;;
    validate) [[ $# -eq 2 ]] || { usage; exit 2; }; python3 "$base/tools/lib.py" validate "$2" ;;
    check) [[ $# -le 2 ]] || { usage; exit 2; }; bash "$base/commands/check.sh" "${2:-}" ;;
    discover-nics) [[ $# -le 2 ]] || { usage; exit 2; }; bash "$base/commands/discover-nics.sh" "${2:-}" ;;
    menu)
        [[ $# -le 1 ]] || { usage; exit 2; }
        printf '1) Collect settings\n2) Check using state/answers.json\n3) Inventory current context\n4) Exit\n5) Discover node NICs (temporary pods; saved context if available)\n'
        ask choice 'Choose' 1
        case $choice in
            1) configure ;;
            2) bash "$base/commands/check.sh" "$base/state/answers.json" ;;
            3) bash "$base/commands/check.sh" ;;
            4) exit 0 ;;
            5)
                config=''
                [[ ! -f "$base/state/answers.json" ]] || config="$base/state/answers.json"
                bash "$base/commands/discover-nics.sh" "$config" ;;
            *) usage; exit 2 ;;
        esac ;;
    *) usage; exit 2 ;;
esac
