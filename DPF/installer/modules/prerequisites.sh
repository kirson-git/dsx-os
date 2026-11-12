#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
source "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/common.sh"
source "$base/modules/log.sh"
mkdir -p "$base/state"
run=$(mktemp -d "$base/state/prereq-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
mkdir -p "$run/tmp" "$base/state/helm/cache" "$base/state/helm/config" "$base/state/helm/data"
export TMPDIR="$run/tmp"
export HELM_CACHE_HOME="$base/state/helm/cache"
export HELM_CONFIG_HOME="$base/state/helm/config"
export HELM_DATA_HOME="$base/state/helm/data"
export HELMFILE_UPGRADE_NOTICE_DISABLED=1
export HELMFILE_CACHE_HOME="$base/state/helmfile/cache"
export XDG_CACHE_HOME="$base/state/cache"

audit_dir=''
finish() {
    local status=$?
    trap - EXIT
    rm -f "$run/kubeconfig"
    if [[ -n "$audit_dir" ]]; then
        python3 "$base/tools/install_log.py" finish --logs "$audit_dir" --exit-code "$status" || true
        printf '\nLogs: %s/logs/latest  (commands.log + phase output)\n' "$base"
    fi
    if [[ $status -ne 0 ]]; then
        printf '\nInstallation stopped (exit %s). Logs: %s\n' "$status" "$run" >&2
    fi
    exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -z "$context" ]]; then context=$(kubectl config current-context); fi
[[ -n "$context" ]] || { echo 'No Kubernetes context selected.' >&2; exit 1; }
if [[ "$dry" == false ]]; then
    audit_dir=$(python3 "$base/tools/install_log.py" start --base "$base" --run "$run" --kind prerequisites --context "$context")
    export DPF_INSTALL_LOG="$audit_dir"
    export PATH="$run/command-bin:$PATH"
fi
k=(kubectl --context="$context" --request-timeout=30s)
printf 'Checking DPF v26.4.0 prerequisites...\n'
printf '%s\n' "$context" > "$run/context.txt"
# Snapshot the selected context so upstream kubectl hooks use the same cluster,
# without changing the administrator's current context. Never print this file.
"${k[@]}" config view --raw --minify --flatten > "$run/kubeconfig"
export KUBECONFIG="$run/kubeconfig"
"${k[@]}" version -o json > "$run/version.json"
version=$(jq -er '.serverVersion.gitVersion' "$run/version.json")
if [[ ! "$version" =~ ^v1\.(33|34|35|36)\. ]]; then
    printf 'Unsupported Kubernetes version: %s (DPF v26.4.0 platform range: 1.33–1.36).\n' "$version" >&2
    exit 1
fi
"${k[@]}" get nodes -o json > "$run/nodes.json"
jq -e '.items | length > 0 and all(.[]; any(.status.conditions[]?; .type == "Ready" and .status == "True"))' \
    "$run/nodes.json" >/dev/null || { echo 'Cluster has missing or unready nodes.' >&2; exit 1; }
"${k[@]}" get storageclasses -o json > "$run/storage.json"
# A status issue is useful inventory, but a failed read must stop installation.
status_code=0
python3 "$base/tools/prereq_status.py" --context "$context" --storage-class "$storage" || status_code=$?
[[ "$status_code" -le 1 ]] || exit "$status_code"
python3 "$base/tools/prepare_prereqs.py" "$base" "$run" "$storage" "$seconds" > "$run/plan.txt"
python3 "$base/tools/kamaji_bootstrap.py" prepare --run "$run" --context "$context"
if [[ "$dry" == true ]]; then
    echo 'Preview complete. No cluster changes.'
    echo 'To install: ./dpf-install.sh --install-prereq (keep any context/storage options).'
    exit 0
fi
printf '\nPreparing installation tools...\n'
log_command "Initialize installation tools" "$run/tools.log" helmfile init --force

apply_state() {
    local state=$1 log=$2
    log_command "Apply $(basename "$state")" "$log" \
        helmfile --kube-context "$context" --file "$state" apply --skip-diff-on-install --concurrency 1
}

if [[ $(cat "$run/needs-bootstrap") == true ]]; then
    echo '[1/3] Starting prerequisites and Kamaji without a default DataStore...'
    apply_state "$run/helmfiles/bootstrap.yaml" "$run/bootstrap.log"
    echo '[2/3] Creating the default DataStore through the Kamaji webhook...'
    log_command "Configure Kamaji DataStore" "$run/datastore.log" python3 "$base/tools/kamaji_bootstrap.py" create --run "$run" --context "$context"
    echo '[3/3] Restoring NVIDIA settings and verifying readiness...'
else
    echo 'Reconciling prerequisite charts and waiting for readiness...'
fi
apply_state "$run/helmfiles/prereqs.yaml" "$run/install.log"
helm --kube-context "$context" list -A -o json > "$run/releases.json"
# Exit 1 only means "something is missing" (dpf-operator is installed next); 2 is a real read error.
status_code=0
python3 "$base/tools/prereq_status.py" --context "$context" --storage-class "$storage" || status_code=$?
[[ "$status_code" -le 1 ]] || exit "$status_code"
echo 'Prerequisites installed and ready.'
