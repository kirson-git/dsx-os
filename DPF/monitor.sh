#!/usr/bin/env bash
# Read-only DPF monitor. Does not release holds, sync Argo, or reboot hardware.
set -euo pipefail
umask 077

usage() {
  cat <<'HELP'
Usage: bash monitor.sh [--panes] [--detach] [--session NAME]
                      [--namespace NAME] [--log-dir DIRECTORY]

Default: attach to four tmux windows in session dpf-monitor.
  --panes          Show the four views together in a tiled window.
  --detach         Start without attaching (prints the attach command).
  --session NAME   Session name; letters, digits, underscore and hyphen only.
  --namespace NAME DPF namespace (default: dpf-operator-system).
  --log-dir DIR    Save logs here (default: $HOME/dpf-logs/TIMESTAMP).
  --help           Show this help.

Views: status, provisioning controller logs, service controller logs, events.
These are Kubernetes/controller logs, not DPU SSH or serial-console logs.
Existing sessions are reused; layout/log options apply only to a new session.
Uses the current Kubernetes context, pinned when the session starts.
Detach: Ctrl+b then d. Next window: Ctrl+b then n. Zoom pane: Ctrl+b then z.
Stop the monitor: tmux kill-session -t dpf-monitor (or your chosen session name).
HELP
}

# Internal pane worker: all cluster operations here are read-only.
if [[ ${1:-} == --view ]]; then
  [[ $# == 5 ]] || exit 2
  view=$2; context=$3; namespace=$4; log_dir=$5
  k=(kubectl --context "$context" -n "$namespace")
  printf 'Context: %s | namespace: %s | view: %s\n' "$context" "$namespace" "$view"
  case "$view" in
    status)
      while true; do
        printf '\033[2J\033[H'
        printf 'DPF STATUS | %s | %s\n' "$context" "$(date -Is)"
        "${k[@]}" --request-timeout=15s get dpus,bfbs,dpunodemaintenances || true
        printf '\nDPU conditions (look for reboot requests or failures):\n'
        "${k[@]}" --request-timeout=15s get dpus -o 'jsonpath={range .items[*]}{.metadata.name}{"\n"}{range .status.conditions[?(@.status=="False")]}{.type}{": "}{.reason}{" "}{.message}{"\n"}{end}{end}' || true
        sleep 5
      done ;;
    provisioning|services)
      if [[ $view == provisioning ]]; then
        component=dpf-provisioning-controller-manager
      else
        component=dpuservice-controller-manager
      fi
      while true; do
        { "${k[@]}" logs -f -l "dpu.nvidia.com/component=$component" \
            --all-containers=true --prefix=true --timestamps=true \
            --tail=100 --since=5m --max-log-requests=20 --ignore-errors=true || true; } \
            2>&1 | tee -a "$log_dir/$view.log"
        printf 'Log stream ended; reconnecting in 5 seconds (recent lines may repeat).\n'
        sleep 5
      done ;;
    events)
      while true; do
        { "${k[@]}" get events --watch --request-timeout=5m || true; } \
          2>&1 | tee -a "$log_dir/events.log"
        sleep 5
      done ;;
    *) exit 2 ;;
  esac
  exit
fi

session=dpf-monitor
namespace=dpf-operator-system
layout=windows
detach=false
log_dir=''
while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --panes) layout=panes; shift ;;
    --detach) detach=true; shift ;;
    --session|--namespace|--log-dir)
      [[ $# -ge 2 && -n $2 ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 2; }
      case "$1" in
        --session) session=$2 ;;
        --namespace) namespace=$2 ;;
        --log-dir) log_dir=$2 ;;
      esac
      shift 2 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ $session =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'Invalid session name' >&2; exit 2; }
for command in tmux kubectl tee; do
  command -v "$command" >/dev/null || { printf 'Install %s first.\n' "$command" >&2; exit 1; }
done
session_id=''
while read -r existing_name existing_id; do
  if [[ $existing_name == "$session" ]]; then session_id=$existing_id; break; fi
done < <(tmux list-sessions -F '#{session_name} #{session_id}' 2>/dev/null || true)
if [[ -z $session_id ]]; then
  context=$(kubectl config current-context)
  kubectl --context "$context" --request-timeout=15s -n "$namespace" get dpus >/dev/null
  log_dir=${log_dir:-"$HOME/dpf-logs/$(date -u +%Y%m%dT%H%M%SZ)"}
  mkdir -p -- "$log_dir"
  log_dir=$(cd -- "$log_dir" && pwd -P)
  script=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/$(basename -- "${BASH_SOURCE[0]}")
  worker() { printf '%q ' bash "$script" --view "$1" "$context" "$namespace" "$log_dir"; }
  # Force Bash so printf %q quoting is interpreted consistently.
  created=$(tmux new-session -d -P -F '#{session_id} #{pane_id}' -s "$session" -n status -x 160 -y 48 bash)
  read -r session_id first <<< "$created"
  trap 'tmux kill-session -t "$session_id" 2>/dev/null || true' ERR
  tmux set-option -t "$session_id" default-shell "$(command -v bash)"
  tmux respawn-pane -k -t "$first" "$(worker status)"
  for view in provisioning services events; do
    if [[ $layout == panes ]]; then
      pane=$(tmux split-window -d -P -F '#{pane_id}' -t "$first" "$(worker "$view")")
      tmux select-pane -t "$pane" -T "$view"
      tmux select-layout -t "$first" tiled >/dev/null
    else
      tmux new-window -d -t "$session_id:" -n "$view" "$(worker "$view")"
    fi
  done
  tmux select-pane -t "$first" -T status
  tmux set-option -w -t "$first" pane-border-status top
  tmux set-option -w -t "$first" pane-border-format '#{pane_title}'
  trap - ERR
  printf 'Log directory: %s\n' "$log_dir"
fi
printf 'Attach: tmux attach -t %s\n' "$session"
if [[ $detach == false ]]; then
  if [[ -n ${TMUX:-} ]]; then
    tmux switch-client -t "$session_id"
  elif [[ -t 0 && -t 1 ]]; then
    exec tmux attach-session -t "$session_id"
  else
    printf 'No interactive terminal; session is running detached.\n'
  fi
fi
