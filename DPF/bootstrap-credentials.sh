#!/usr/bin/env bash
# Two-command clean install, command 1. Passwords never appear in argv or logs.
set +x
set -euo pipefail
umask 077
dsx_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
dsx_bmc_file=''
dsx_idrac_file=''
dsx_idrac_user=root
usage() {
  cat <<'EOF'
Usage: bash DPF/bootstrap-credentials.sh [--bmc-password-file PATH]
       [--idrac-password-file PATH] [--idrac-user USER]

For the single-Application clean install with DPF-native host reboot.
Requires external Argo in the current kubectl cluster; rejects existing staged
DPF Applications. Creates dpf-operator-system and two private Secrets.
Missing passwords are read from hidden prompts. Files must be outside Git,
mode 600/400, nonempty and without newlines. iDRAC user defaults to root.
Run only after the agreed DPF cleanup. This command does not delete or reboot.
EOF
}
fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
while (($#)); do
  case $1 in
    --bmc-password-file|--idrac-password-file|--idrac-user)
      (($# >= 2)) || fail "$1 needs a value"
      case $1 in
        --bmc-password-file) dsx_bmc_file=$2 ;;
        --idrac-password-file) dsx_idrac_file=$2 ;;
        --idrac-user) dsx_idrac_user=$2 ;;
      esac
      shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done
[[ -n "$dsx_idrac_user" && "$dsx_idrac_user" != *:* && "$dsx_idrac_user" != *$'\n'* && "$dsx_idrac_user" != *$'\r'* ]] || fail 'Invalid iDRAC username'
dsx_root=$(cd -- "$dsx_dir/.." && pwd -P)
dsx_temp_root=$(cd -- "${TMPDIR:-/tmp}" && pwd -P)
case "$dsx_temp_root" in "$dsx_root"|"$dsx_root"/*) fail 'TMPDIR must be outside the repository' ;; esac
dsx_private=$(mktemp -d "$dsx_temp_root/dsx-bootstrap.XXXXXXXX")
trap 'unset dsx_password; rm -rf -- "$dsx_private"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
read_password() {
  local source=$1 label=$2 destination=$3 resolved mode
  dsx_password=''
  if [[ -n "$source" ]]; then
    [[ -f "$source" && -r "$source" && ! -L "$source" ]] || fail 'Use a readable regular credential file'
    resolved="$(cd -- "$(dirname -- "$source")" && pwd -P)/$(basename -- "$source")"
    case "$resolved" in "$dsx_root"|"$dsx_root"/*) fail 'Credentials must be outside the repository' ;; esac
    mode=$(stat -c '%a' "$resolved" 2>/dev/null || stat -f '%Lp' "$resolved")
    [[ "$mode" == 600 || "$mode" == 400 ]] || fail 'Credential files must have mode 600/400'
    if IFS= read -r dsx_password < "$resolved"; then fail 'Password files must contain no newline'; fi
  else
    [[ -t 0 ]] || fail 'Use password-file options when not running interactively'
    IFS= read -r -s -p "$label: " dsx_password
    printf '\n'
  fi
  [[ -n "$dsx_password" && "$dsx_password" != *$'\r'* ]] || fail 'Empty password or carriage return'
  printf '%s' "$dsx_password" > "$destination"
  unset dsx_password
}
read_password "$dsx_bmc_file" 'DPF shared DPU BMC password' "$dsx_private/bmc"
read_password "$dsx_idrac_file" 'Shared host iDRAC password (Europe and Asia)' "$dsx_private/password"
printf '%s' "$dsx_idrac_user" > "$dsx_private/username"
kubectl get crd applications.argoproj.io >/dev/null
dsx_conflicts=$(kubectl -n argocd get applications dpf-platform dpf-site dpf-hbn dpf-provisioning dpf-operator-config dpf-tenants --ignore-not-found -o name)
[[ -z "$dsx_conflicts" ]] || fail 'Staged DPF Applications still exist. Complete the agreed cleanup before using the single Application; no changes made.'
printf 'Creating namespace and private password Secrets in the current kubectl cluster.\n'
kubectl create namespace dpf-operator-system --dry-run=client -o yaml | kubectl apply --server-side --field-manager=dsx-private-credentials -f -
bash "$dsx_dir/credentials.sh" --password-file "$dsx_private/bmc"
if ! kubectl create secret generic dpf-host-reboot-credentials -n dpf-operator-system \
    --from-file=username="$dsx_private/username" --from-file=password="$dsx_private/password" \
    --dry-run=client -o yaml > "$dsx_private/secret.yaml" 2> "$dsx_private/error"; then
  fail 'Could not prepare iDRAC Secret; no secret content logged'
fi
if ! kubectl apply --server-side --field-manager=dsx-private-credentials -f - \
    < "$dsx_private/secret.yaml" > "$dsx_private/result" 2> "$dsx_private/error"; then
  fail 'Could not apply iDRAC Secret; check cluster access and field ownership'
fi
printf 'Saved bmc-shared-password and dpf-host-reboot-credentials. Values hidden.\n'
