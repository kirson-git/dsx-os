#!/usr/bin/env bash
# All cluster commands used by Part 1 are visible here. No writes to Kubernetes.
set -euo pipefail
umask 077
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
for tool in python3 kubectl helm timeout; do
    command -v "$tool" >/dev/null || { printf 'Missing tool: %s\n' "$tool" >&2; exit 1; }
done
config=${1:-}
if [[ -n "$config" ]]; then
    python3 "$base/tools/lib.py" validate "$config"
    context=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["context"])' "$config")
else
    context=$(kubectl config current-context)
fi
[[ -n "$context" ]] || { echo 'No Kubernetes context selected.' >&2; exit 1; }
mkdir -p "$base/state"
run=$(mktemp -d "$base/state/check-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
printf '%s\n' "$context" > "$run/context.txt"
printf 'Reading Kubernetes context: %s\nReport directory: %s\n' "$context" "$run"
capture() {
    local name=$1
    shift
    if timeout 45 "$@" > "$run/$name.json" 2> "$run/$name.stderr"; then
        rm -f "$run/$name.stderr"
    else
        printf 'Could not read %s; see %s/%s.stderr\n' "$name" "$run" "$name" >&2
        # Keep the failure marker even when the command emitted no stderr.
    fi
}
k=(kubectl --context="$context" --request-timeout=20s)
capture version "${k[@]}" version -o json
capture nodes "${k[@]}" get nodes -o json
capture storage "${k[@]}" get storageclasses -o json
capture deployments "${k[@]}" get deployments -A -o json
capture releases helm --kube-context "$context" list -A --deployed --failed --pending --uninstalled --uninstalling --superseded --max 1000 -o json
python3 "$base/tools/lib.py" report "$run" "$config" | tee "$run/report.txt"
