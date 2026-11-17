#!/usr/bin/env bash
# Standalone DPF v26.4.0: NVIDIA prerequisite Helmfile entrypoint.
set -Eeuo pipefail
umask 077
source "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/common.sh"

if [[ ${1:-} == --sanity ]]; then
    shift
    exec bash "$base/sanity-check/sanity-check.sh" "$@"
fi
usage() {
    cat <<'EOF'
Usage: ./dpf-install.sh ACTION [options]

Actions:
  --verify              Read-only component/version/readiness table.
  --install-prereq      Install/reconcile NVIDIA's prerequisite Helmfile.
  --install-dpf         Install DPF v26.4.0 operator after prerequisite checks.
  --diagnose            Read status plus pod/PVC problems and recent warning events.
  --check-bmc           Guided node/NIC/BMC setup and Redfish authentication check.
                        Uses a temporary hostNetwork pod; password is not saved.
  --discover-dpus       Scan a prompted BMC IPv4 range from a temporary Kubernetes
                        pod; ask for username/password and report Redfish devices.
  --clean               Preview full DPF lab reset: releases, CRDs, Secrets and ConfigMaps.
  --sanity [OPTIONS]    First flag only: run the modular DPF sanity checks.

Install the pre-DPF charts from NVIDIA/doca-platform v26.4.0 deploy/helmfiles.
Required: cert-manager, Argo CD, Node Feature Discovery, Maintenance Operator.
Default topology: Kamaji and Local Path Provisioner (only if storage is absent).
The DPF action installs the operator only; runtime configuration and DPU provisioning follow separately.

With no arguments: show this help without accessing the cluster.
Select one action. Options alone require an action, except --more (implies --verify).

Examples:
  ./dpf-install.sh --verify
  ./dpf-install.sh --install-prereq --dry-run
  ./dpf-install.sh --install-prereq
  ./dpf-install.sh --install-dpf
  ./dpf-install.sh --verify --context YOUR_CONTEXT

Options:
  --delete-storage      With --clean only: also delete lab PVCs and bound PVs.
                        Storage provisioner and StorageClasses remain installed.
  --force-finalizers    With --clean only: also release objects that are stuck in
                        deletion (already marked for deletion, held by a finalizer).
                        Use only when what they wait for is already gone.
  --yes                 With --clean only: execute the displayed cleanup scope.
  --more                With --verify/--diagnose/--clean: show detailed information.
  --context NAME        Target kubeconfig context (default: current context).
  --storage-class NAME  Reuse this class for Kamaji etcd (default: local-path).
                        An existing provisioner is retained regardless of version.
                        If local-path is absent, install the bundled v0.0.34 chart.
                        A missing custom class is an error.
  --timeout SECONDS     Helm release readiness timeout; positive integer, default 600.
                        Upstream hook-specific timeouts are preserved.
  --dry-run             With either install action: preview only; no cluster changes.
                        No downloads, plugin initialization or cluster changes.
  --help                Show this help.

Compatibility:
  --status              Alias for --verify.
  --menu                Open the legacy menu explicitly.

Status needs bash, kubectl, helm and python3 with PyYAML.
Installation also needs helmfile and jq. NIC scan needs timeout and pod permissions.
Installation logs: logs/latest.log (steps/output) and logs/latest/ (command audit).
Temporary files, Helm caches/plugins and generated YAML stay in state/.
The real install initializes Helmfile's local dependencies, then applies the
generated Helmfile. Failures stop the run; no automatic uninstall or policy bypass.
Status exit: 0 all checks pass, 1 missing/unready/review needed, 2 read/usage error.
Install exit: 0 success, 2 usage error, nonzero on preflight/installation failure.
EOF
}

if (( $# == 0 )); then usage; exit 0; fi

action=false dpf=false bmc=false discover=false status=false menu=false diagnose=false clean=false delete_storage=false force_finalizers=false yes=false more=false dry=false context='' storage=local-path seconds=600
while [[ $# -gt 0 ]]; do
    case $1 in
        --install-prereq) action=true; shift ;;
        --install-dpf) dpf=true; shift ;;
        --check-bmc) bmc=true; shift ;;
        --discover-dpus) discover=true; shift ;;
        --verify|--status) status=true; shift ;;
        --menu) menu=true; shift ;;
        --diagnose) diagnose=true; shift ;;
        --clean) clean=true; shift ;;
        --delete-storage) delete_storage=true; shift ;;
        --force-finalizers) force_finalizers=true; shift ;;
        --yes) yes=true; shift ;;
        --more) more=true; shift ;;
        --dry-run) dry=true; shift ;;
        --context|--storage-class|--timeout)
            [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { usage >&2; exit 2; }
            case $1 in
                --context) context=$2 ;;
                --storage-class) storage=$2 ;;
                --timeout) seconds=$2 ;;
            esac
            shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done
actions=0
for selected in "$action" "$status" "$menu" "$diagnose" "$clean" "$dpf" "$bmc" "$discover"; do
    if [[ "$selected" == true ]]; then actions=$((actions + 1)); fi
done
if (( actions > 1 )) || [[ "$action" == false && "$dpf" == false && "$dry" == true ]] || [[ ( "$yes" == true || "$delete_storage" == true || "$force_finalizers" == true ) && "$clean" == false ]]; then
    usage >&2; exit 2
fi
if [[ "$more" == true && ( "$action" == true || "$dpf" == true || "$bmc" == true || "$discover" == true || "$menu" == true ) ]]; then
    usage >&2; exit 2
fi
if [[ "$more" == true && "$diagnose" == false && "$clean" == false ]]; then status=true; actions=1; fi
if (( actions == 0 )); then usage >&2; exit 2; fi
[[ "$seconds" =~ ^[1-9][0-9]*$ && ${#seconds} -le 6 ]] || { echo 'Timeout must be 1–999999 seconds.' >&2; exit 2; }
[[ "$storage" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || { echo 'Invalid StorageClass name.' >&2; exit 2; }
required=(kubectl helm python3)
if [[ "$bmc" == true || "$discover" == true ]]; then required=(kubectl python3); fi
if [[ "$action" == true ]]; then required+=(helmfile jq); fi
for tool in "${required[@]}"; do
    command -v "$tool" >/dev/null || { printf 'Missing tool: %s\n' "$tool" >&2; exit 1; }
done
if [[ "$discover" == true ]]; then
    if [[ -z "$context" ]]; then context=$(kubectl config current-context); fi
    [[ -n "$context" ]] || { echo 'No Kubernetes context selected.' >&2; exit 1; }
    exec bash "$base/modules/discovery.sh" --context "$context"
fi
if [[ "$bmc" == true ]]; then
    if [[ -z "$context" ]]; then context=$(kubectl config current-context); fi
    exec bash "$base/modules/bmc.sh" --context "$context"
fi
if [[ "$dpf" == true ]]; then
    if [[ -z "$context" ]]; then context=$(kubectl config current-context); fi
    [[ -n "$context" ]] || { echo 'No Kubernetes context selected.' >&2; exit 1; }
    exec bash "$base/modules/dpf.sh" "$context" "$storage" "$seconds" "$dry"
fi
if [[ "$clean" == true ]]; then
    extra=()
    if [[ "$yes" == true ]]; then extra+=(--yes); fi
    if [[ "$delete_storage" == true ]]; then extra+=(--delete-storage); fi
    if [[ "$force_finalizers" == true ]]; then extra+=(--force-finalizers); fi
    if [[ "$more" == true ]]; then extra+=(--more); fi
    exec bash "$base/modules/uninstall.sh" --context "$context" --timeout "$seconds" "${extra[@]}"
fi
if [[ "$menu" == true ]]; then
    exec bash "$base/modules/menu.sh" "$context" "$storage" "$seconds"
fi
if [[ "$action" == false ]]; then
    extra=()
    if [[ "$diagnose" == true ]]; then extra+=(--diagnose); fi
    if [[ "$more" == true ]]; then extra+=(--more); fi
    exec python3 "$base/tools/prereq_status.py" --context "$context" --storage-class "$storage" "${extra[@]}"
fi
source "$base/modules/prerequisites.sh"
