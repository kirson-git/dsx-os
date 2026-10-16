#!/usr/bin/env bash
# Never trace credential input, even if the caller used bash -x.
set +x
set -euo pipefail

dsx_repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
dsx_source=''
usage() {
  cat <<'EOF'
Usage: bash DPF/credentials.sh [--password-file /outside/repo/private-file]

Create/update dpf-operator-system/bmc-shared-password in the current kubectl
cluster. Without a file, read the BMC password from a hidden terminal prompt.
File input must be outside the repository, mode 600/400, without a newline.
The namespace must already exist. No DPU Linux password is changed.
EOF
}
fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
case ${1:-} in
  --help|-h) usage; exit 0 ;;
  --password-file) [[ $# -eq 2 ]] || fail '--password-file requires exactly one path'; dsx_source=$2 ;;
  '') ;;
  *) usage >&2; exit 1 ;;
esac
umask 077
dsx_temp_root=$(cd -- "${TMPDIR:-/tmp}" && pwd -P) || fail 'Temporary directory is inaccessible'
case "$dsx_temp_root" in
  "$dsx_repo_dir"|"$dsx_repo_dir"/*) fail 'Temporary directory must be outside the repository' ;;
esac
if [[ -n "$dsx_source" ]]; then
  [[ -f "$dsx_source" && -r "$dsx_source" && ! -L "$dsx_source" ]] || fail 'Use a readable regular file, not a symlink'
  dsx_source="$(cd -- "$(dirname -- "$dsx_source")" && pwd -P)/$(basename -- "$dsx_source")"
  case "$dsx_source" in "$dsx_repo_dir"/*) fail 'Credential file must be outside the repository' ;; esac
  dsx_mode=$(stat -c '%a' "$dsx_source" 2>/dev/null || stat -f '%Lp' "$dsx_source")
  [[ "$dsx_mode" == 600 || "$dsx_mode" == 400 ]] || fail 'Credential file must have mode 600 or 400'
  dsx_password=''
  if IFS= read -r dsx_password < "$dsx_source"; then
    fail 'Password file must contain no newline'
  fi
else
  [[ -t 0 ]] || fail 'Use an interactive terminal or --password-file'
  IFS= read -r -s -p 'DPF shared BMC password: ' dsx_password
  printf '\n'
fi
[[ -n "$dsx_password" && "$dsx_password" != *$'\r'* ]] || fail 'Password must be nonempty and contain no carriage return'
dsx_private_dir=$(mktemp -d "$dsx_temp_root/dsx-credentials.XXXXXXXX")
trap 'unset dsx_password; rm -rf -- "$dsx_private_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
printf '%s' "$dsx_password" > "$dsx_private_dir/password"
unset dsx_password
# No credential values in argv or repository files. Suppress API errors because
# admission responses can echo Secret contents; private temporary files are removed.
if ! kubectl create secret generic bmc-shared-password -n dpf-operator-system \
  --from-file=password="$dsx_private_dir/password" --dry-run=client -o yaml \
  > "$dsx_private_dir/secret.yaml" 2> "$dsx_private_dir/create-error"; then
  fail 'Secret preparation failed; check kubectl and local input. No secret output was logged'
fi
if ! kubectl apply --server-side --field-manager=dsx-private-credentials -f - \
  < "$dsx_private_dir/secret.yaml" > "$dsx_private_dir/result" 2> "$dsx_private_dir/apply-error"; then
  fail 'Secret write failed; check context, RBAC, namespace and field ownership. No secret output was logged'
fi
printf 'Saved Secret dpf-operator-system/bmc-shared-password; value not displayed.\n'
