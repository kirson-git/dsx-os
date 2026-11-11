#!/usr/bin/env bash
# Explicit sanity actions share the installer log and module presentation.
set -Eeuo pipefail
umask 077
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mode=prereq context='' storage=local-path more=false selected=0
while (($#)); do
    case $1 in
        --prereq|--hardware|--storage|--nics|--bmc|--diagnose)
            mode=${1#--}; selected=$((selected+1)); shift ;;
        --context|--storage-class)
            [[ $# -ge 2 && -n $2 && $2 != --* ]] || exit 2
            if [[ $1 == --context ]]; then context=$2; else storage=$2; fi
            shift 2 ;;
        --more) more=true; shift ;;
        --help|-h)
            cat <<'EOF'
Usage: ./dpf-install.sh --sanity [--prereq|--hardware|--storage|--nics|--bmc|--diagnose] [options]
Default: --prereq (component versions and readiness).
--hardware: read control-plane capacity, architecture and node pressure.
--storage: create a temporary 64Mi PVC/pod, verify read/write, and remove it.
--nics: temporary node-network NIC inventory pods.
--bmc: guided node/NIC/BMC credential test with a temporary node-network pod.
--diagnose: read pod/PVC failures and warning events.
Options: --context NAME, --storage-class NAME (default local-path), --more.
--more applies only to --prereq/--diagnose. Select at most one check.
Logs: logs/latest.log and logs/latest/. Checks do not install DPF or NICo.
EOF
            exit 0 ;;
        *) printf 'Unknown sanity option: %s\n' "$1" >&2; exit 2 ;;
    esac
done
((selected<=1)) || { echo 'Choose one sanity check.' >&2; exit 2; }
[[ $more == false || $mode == prereq || $mode == diagnose ]] || exit 2
for tool in kubectl python3; do command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }; done
[[ -n $context ]] || context=$(kubectl config current-context)
mkdir -p "$base/state"
run=$(mktemp -d "$base/state/sanity-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
audit_dir=$(python3 "$base/tools/install_log.py" start --base "$base" --run "$run" --kind "sanity-$mode" --context "$context")
export DPF_INSTALL_LOG="$audit_dir" PATH="$run/command-bin:$PATH"
finish() {
    local code=$?
    trap - EXIT
    python3 "$base/tools/install_log.py" finish --logs "$audit_dir" --exit-code "$code" || true
    printf '\nLog: %s/logs/latest.log\n' "$base"
    exit "$code"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
args=(--context "$context")
case $mode in
    prereq|diagnose)
        cmd=(python3 "$base/tools/prereq_status.py" "${args[@]}" --storage-class "$storage")
        [[ $mode != diagnose ]] || cmd+=(--diagnose)
        [[ $more == false ]] || cmd+=(--more) ;;
    hardware|storage) cmd=(bash "$base/sanity-check/modules/$mode.sh" "${args[@]}" --storage-class "$storage") ;;
    nics) cmd=(bash "$base/sanity-check/nics.sh" "${args[@]}") ;;
    bmc) cmd=(bash "$base/modules/bmc.sh" "${args[@]}") ;;
esac
python3 "$base/tools/install_log.py" phase --show-output "Sanity: $mode" "$run/install.log" "${cmd[@]}"
