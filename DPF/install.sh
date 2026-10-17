#!/usr/bin/env bash
# Small Bash front end; desired DPF state stays in the supplied Argo Application.
set +x
set -euo pipefail
umask 077
dsx_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
dsx_config=''
dsx_action=menu
dsx_bmc_file=''
dsx_idrac_file=''
dsx_idrac_user=root
dsx_probe_args=()
usage() {
  cat <<'EOF'
Usage: bash DPF/install.sh --config /path/to/install.yaml [--action ACTION]
       [--bmc-password-file PATH] [--idrac-password-file PATH] [--idrac-user USER]
       [--insecure-bmc]

Actions: menu (default), config, all, argo, passwords, dpf, status, delete-plan, delete.
all: install/upgrade external Argo using Helm, create private Secrets, apply the
single DPF Application. Argo continues asynchronously. No automatic deletion.
delete: remove this two-tenant DPF stack, dedicated prerequisites and their CRDs,
then external Argo and its CRDs. Requires typing the current kubectl context.
Keeps Kubernetes, Calico/network-policy CRDs, Ubuntu hosts and external networking.
Requires bash, kubectl, Helm, python3 and PyYAML. Config must be the prepared
single Application from TWO-COMMAND-INSTALL.md, not the old staged config.yaml.
Commands and non-secret output are logged under /tmp/dsx-installer.* by default.
Passwords are validated from a temporary pod before saving Secrets.
--insecure-bmc disables BMC certificate verification for self-signed lab devices.
EOF
}
fail() { printf 'ERROR: %s\n' "$1" >&2; return 1; }
while (($#)); do
  case $1 in
    --config|--action|--bmc-password-file|--idrac-password-file|--idrac-user)
      (($# >= 2)) || { fail "$1 needs a value"; exit 1; }
      case $1 in
        --config) dsx_config=$2 ;;
        --action) dsx_action=$2 ;;
        --bmc-password-file) dsx_bmc_file=$2 ;;
        --idrac-password-file) dsx_idrac_file=$2 ;;
        --idrac-user) dsx_idrac_user=$2 ;;
      esac
      shift 2 ;;
    --help|-h) usage; exit 0 ;;
    --insecure-bmc) dsx_probe_args+=(--insecure-bmc); shift ;;
    *) fail "Unknown argument: $1"; exit 1 ;;
  esac
done
for dsx_tool in kubectl helm python3; do
  command -v "$dsx_tool" >/dev/null || { fail "Missing command: $dsx_tool"; exit 1; }
done
python3 -c 'import yaml' || { fail 'Install PyYAML for python3 before continuing'; exit 1; }
dsx_log_dir=$(mktemp -d "${TMPDIR:-/tmp}/dsx-installer.XXXXXXXX")
dsx_log="$dsx_log_dir/installer.log"
exec > >(tee -a "$dsx_log") 2>&1
printf 'Log: %s\n' "$dsx_log"
run() { printf '+ '; printf '%q ' "$@"; printf '\n'; "$@"; }
show_config() {
  [[ -n "$dsx_config" ]] || { fail 'Supply --config /path/to/your/install.yaml'; return 1; }
  python3 "$dsx_dir/tools/installer.py" config --config "$dsx_config"
}
install_argo() {
  run helm repo add argo https://argoproj.github.io/argo-helm || return
  run helm repo update argo || return
  local reuse=()
  if helm status external-argo-cd --namespace argocd >/dev/null 2>&1; then reuse=(--reuse-values); fi
  run helm upgrade --install external-argo-cd argo/argo-cd \
    --version 9.4.1 --namespace argocd --create-namespace "${reuse[@]}" \
    --set configs.cm.installationID=dsx-platform \
    -f "$dsx_dir/values/external-argo.yaml" --wait --timeout 10m
}
set_passwords() {
  local args=(--config "$dsx_config" --idrac-user "$dsx_idrac_user" "${dsx_probe_args[@]}")
  [[ -z "$dsx_bmc_file" ]] || args+=(--bmc-password-file "$dsx_bmc_file")
  [[ -z "$dsx_idrac_file" ]] || args+=(--idrac-password-file "$dsx_idrac_file")
  bash "$dsx_dir/bootstrap-credentials.sh" "${args[@]}"
}
install_dpf() {
  show_config || return
  local conflicts
  conflicts=$(kubectl -n argocd get applications dpf-platform dpf-site dpf-hbn dpf-provisioning dpf-operator-config dpf-tenants --ignore-not-found -o name) || return
  [[ -z "$conflicts" ]] || { fail 'Staged Applications remain; use the reviewed full cleanup first'; return 1; }
  run kubectl apply -f "$dsx_config" || return
  printf 'Argo auto-sync started. Use Status to follow provisioning; closing this menu does not stop it.\n'
}
status() {
  run kubectl get nodes -o wide || return
  run kubectl -n argocd get applications || return
  run kubectl get dpuclusters -A || return
  run kubectl -n dpf-operator-system get dpus || return
  run kubectl -n dpf-operator-system get jobs
}
delete_all() {
  python3 "$dsx_dir/tools/installer.py" delete-plan || return
  local context confirmation
  context=$(kubectl config current-context) || return
  [[ -t 0 ]] || { fail 'Full delete needs an interactive terminal for the cluster-name confirmation'; return 1; }
  printf '\nThis removes DPF, both tenants, their data, dedicated prerequisites and external Argo, including their CRDs.\n'
  printf 'Kubernetes and external host/DHCP/router/switch configuration stay.\n'
  printf 'To delete, type the exact context: %s\n' "$context"
  IFS= read -r confirmation
  [[ "$confirmation" == "$context" ]] || { fail 'Context did not match; nothing deleted'; return 1; }
  python3 "$dsx_dir/tools/installer.py" delete --confirm-context "$confirmation"
}
do_action() {
  case $1 in
    config) show_config ;;
    argo) install_argo ;;
    passwords) set_passwords ;;
    dpf) install_dpf ;;
    status) status ;;
    delete-plan) python3 "$dsx_dir/tools/installer.py" delete-plan ;;
    delete) delete_all ;;
    all)
      show_config || return
      install_argo || return
      set_passwords || return
      install_dpf ;;
    *) fail "Unknown action: $1" ;;
  esac
}
if [[ "$dsx_action" != menu ]]; then do_action "$dsx_action"; exit; fi
[[ -t 0 ]] || { fail 'Use --action when stdin is not a terminal'; exit 1; }
if [[ -n "$dsx_config" ]]; then show_config || true; fi
while :; do
  cat <<'EOF'

DPF installer
  1  Show config
  2  Install all: Argo → passwords → DPF Application
  3  Install/upgrade external Argo only
  4  Set private passwords
  5  Apply DPF Application
  6  Status
  7  Preview full deletion (read only)
  8  Full delete: DPF + prerequisites + Argo + their CRDs
  0  Exit
EOF
  IFS= read -r -p 'Choose: ' dsx_choice || break
  case "$dsx_choice" in
    1) dsx_selected=config ;; 2) dsx_selected=all ;; 3) dsx_selected=argo ;;
    4) dsx_selected=passwords ;; 5) dsx_selected=dpf ;; 6) dsx_selected=status ;;
    7) dsx_selected=delete-plan ;; 8) dsx_selected=delete ;; 0) break ;;
    *) printf 'Choose 0–8.\n'; continue ;;
  esac
  if do_action "$dsx_selected"; then printf 'Command completed.\n'; else printf 'Stopped; inspect %s before retrying.\n' "$dsx_log"; fi
done
