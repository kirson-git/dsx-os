#!/usr/bin/env bash
# Stage 1 of physical-lab DPF setup: the NVIDIA operator, before runtime configuration.
set -Eeuo pipefail
umask 077
source "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/common.sh"
source "$base/modules/log.sh"
context=${1:?context required}
storage=${2:?storage class required}
seconds=${3:?timeout required}
dry=${4:-false}
k=(kubectl --context="$context" --request-timeout=30s)
h=(helm --kube-context "$context")

if ! python3 "$base/tools/prereq_status.py" --context "$context" --storage-class "$storage"; then
    echo 'DPF blocked: prerequisites need attention. Use 3 or M.' >&2
    exit 1
fi
# Retained configuration could make a newly installed operator immediately act
# on DPUs. Keep this training stage limited to operator installation.
resources=$("${k[@]}" api-resources --verbs=list -o name)
while IFS= read -r resource; do
    case "$resource" in
        dpfoperatorconfigs.operator.dpu.nvidia.com|dpusets.provisioning.dpu.nvidia.com|dpus.provisioning.dpu.nvidia.com)
            inventory=$("${k[@]}" get "$resource" -A -o json)
            if ! printf '%s' "$inventory" | python3 -c 'import json,sys; sys.exit(0 if not json.load(sys.stdin)["items"] else 1)'; then
                printf 'DPF blocked: existing %s. Review runtime configuration before installing the operator.\n' "$resource" >&2
                exit 1
            fi ;;
    esac
done <<< "$resources"
if [[ "$dry" == true ]]; then
    printf '\nCOMPONENT      VERSION    ACTION\ndpf-operator   v26.4.0   Install/reconcile\n'
    exit 0
fi
mkdir -p "$base/state"
run=$(mktemp -d "$base/state/dpf-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
mkdir -p "$run/tmp" "$base/state/helm/cache" "$base/state/helm/config" "$base/state/helm/data"
export TMPDIR="$run/tmp"
export HELM_CACHE_HOME="$base/state/helm/cache"
export HELM_CONFIG_HOME="$base/state/helm/config"
export HELM_DATA_HOME="$base/state/helm/data"
export XDG_CACHE_HOME="$base/state/cache"
export HELM_CONTENT_CACHE="$base/state/helm/content"
audit_dir=$(python3 "$base/tools/install_log.py" start --base "$base" --run "$run" --kind dpf-operator --context "$context")
export DPF_INSTALL_LOG="$audit_dir"
export PATH="$run/command-bin:$PATH"
finish() {
    local code=$?
    trap - EXIT
    python3 "$base/tools/install_log.py" finish --logs "$audit_dir" --exit-code "$code" || true
    printf '\nLogs: %s/logs/latest  (commands.log + phase output)\n' "$base"
    if (( code != 0 )); then printf '\nDPF install stopped. Logs: %s\n' "$run" >&2; fi
    exit "$code"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '\nInstalling DPF v26.4.0...\n'
log_command "Add NVIDIA Helm repository" "$run/repository.log" \
    "${h[@]}" repo add --force-update dpf-repository https://helm.ngc.nvidia.com/nvidia/doca
log_command "Refresh NVIDIA Helm repository" "$run/repository.log" "${h[@]}" repo update dpf-repository
log_command "Install DPF v26.4.0 operator" "$run/install.log" \
    "${h[@]}" upgrade --install dpf-operator dpf-repository/dpf-operator \
    --namespace dpf-operator-system --create-namespace --version v26.4.0 \
    --wait --timeout "${seconds}s"
log_command "Verify DPF operator rollout" "$run/rollout.log" \
    "${k[@]}" -n dpf-operator-system rollout status deployment/dpf-operator-controller-manager --timeout="${seconds}s"
# Helm 4 status omits chart metadata; list exposes the chart in Helm 3 and 4.
"${h[@]}" list -n dpf-operator-system --filter '^dpf-operator$' --deployed -o json > "$run/release.json"
python3 - "$run/release.json" <<'PY'
import json,sys
releases=json.load(open(sys.argv[1]))
if not isinstance(releases, list) or len(releases) != 1:
    sys.exit('Expected one deployed DPF release at v26.4.0')
release=releases[0]
if (not isinstance(release, dict)
        or release.get('name') != 'dpf-operator'
        or release.get('namespace') != 'dpf-operator-system'
        or release.get('status') != 'deployed'
        or release.get('chart') not in ('dpf-operator-v26.4.0', 'dpf-operator-26.4.0')):
    sys.exit('DPF release is not deployed at v26.4.0')
PY
printf '\nCOMPONENT      VERSION    STATUS\ndpf-operator   v26.4.0   Ready\n'
