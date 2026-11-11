#!/usr/bin/env bash
# Explicit opt-in: creates temporary hostNetwork pods, reads logs, removes pods.
set -euo pipefail
umask 077
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
for tool in python3 kubectl timeout; do
    command -v "$tool" >/dev/null || { printf 'Missing tool: %s\n' "$tool" >&2; exit 1; }
done
config=${1:-}
if [[ "$config" == --context ]]; then
    [[ $# -eq 2 && -n "$2" ]] || { echo 'Usage: discover-nics.sh --context NAME' >&2; exit 2; }
    context=$2
elif [[ -n "$config" ]]; then
    python3 "$base/tools/lib.py" validate "$config"
    context=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["context"])' "$config")
else
    context=$(kubectl config current-context)
fi
[[ -n "$context" ]] || { echo 'No context selected.' >&2; exit 1; }
k=(kubectl --context="$context" --request-timeout=20s)
mkdir -p "$base/state"
run=$(mktemp -d "$base/state/nics-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
mkdir "$run/manifests"
printf '%s\n' "$context" > "$run/context.txt"
printf 'NIC discovery in context %s; temporary hostNetwork pods in default.\n' "$context"
printf 'Reports: %s\n' "$run"
timeout 30 "${k[@]}" get nodes -l kubernetes.io/os=linux -o json > "$run/nodes.json"
python3 -c 'import json,sys; print("\n".join(n["metadata"]["name"] for n in json.load(open(sys.argv[1]))["items"]))' \
    "$run/nodes.json" > "$run/names.txt"

cleanup() {
    local result=$? manifest
    trap - EXIT
    for manifest in "$run"/manifests/*.json; do
        [[ -f "$manifest" ]] || continue
        if ! timeout 35 "${k[@]}" delete -f "$manifest" --ignore-not-found --wait=true --timeout=25s \
            >> "$run/cleanup.log" 2>&1; then
            printf 'Cleanup failed: inspect %s/cleanup.log; remove only the pods in %s/manifests.\n' "$run" "$run" >&2
            result=1
        fi
    done
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

while IFS= read -r node; do
    [[ -n "$node" ]] || continue
    pod="dpf-nic-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:20])')"
    manifest="$run/manifests/$pod.json"
    python3 "$base/tools/nics.py" manifest "$node" "$pod" > "$manifest"
    printf 'Inspecting %s ...\n' "$node"
    if ! timeout 30 "${k[@]}" create -f "$manifest" > "$run/$node.create.log" 2>&1; then
        touch "$run/$node.failed"
        printf 'Probe creation failed on %s; see %s/%s.create.log\n' "$node" "$run" "$node" >&2
        continue
    fi
    if ! timeout 155 "${k[@]}" -n default wait "pod/$pod" \
        --for=jsonpath='{.status.phase}'=Succeeded --timeout=150s > "$run/$node.wait.log" 2>&1; then
        touch "$run/$node.failed"
        timeout 30 "${k[@]}" -n default describe "pod/$pod" > "$run/$node.describe.txt" 2>&1 || true
    fi
    if ! timeout 30 "${k[@]}" -n default logs "$pod" > "$run/$node.json" 2> "$run/$node.logs.stderr"; then
        touch "$run/$node.failed"
    fi
done < "$run/names.txt"
python3 "$base/tools/nics.py" report "$run" | tee "$run/report.txt"
