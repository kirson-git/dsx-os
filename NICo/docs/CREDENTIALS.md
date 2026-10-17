# Private credentials

Run from the repository root after README Step 3. All commands use the active
kubectl context. Files must be outside the checkout and mode `600` or `400`.
The helper refuses symlinks and never prints secret values.

## 1. Registry access

Use a Harbor robot account with pull access to your image and OCI chart projects.
The image and chart registry must use the same hostname for this helper.

```bash
install -d -m 700 "$HOME/nico-private/docker"
docker --config "$HOME/nico-private/docker" login harbor.runailabs-ps.com
chmod 600 "$HOME/nico-private/docker/config.json"
python3 NICo/scripts/private-bootstrap.py registry \
  --config "$HOME/nico-config.yaml" \
  --dockerconfig "$HOME/nico-private/docker/config.json"
```

Change the hostname to yours. The file must contain embedded `auths`, not only a
credential-helper reference. This creates image-pull Secrets in `nico-system`
and `dpf-operator-system`, an OCI repository Secret for service Argo, and a
random HBN password if absent. Existing HBN passwords are preserved.

## 2. BMC and UEFI site credentials

```bash
umask 077
cat > "$HOME/nico-private/credentials.yaml" <<'YAML'
bmcRootPassword: "REPLACE_WITH_SITE_BMC_PASSWORD"
hostUEFIPassword: "REPLACE_WITH_HOST_UEFI_PASSWORD"
dpuUEFIPassword: "REPLACE_WITH_DPU_UEFI_PASSWORD"
YAML
vi "$HOME/nico-private/credentials.yaml"
python3 NICo/scripts/private-bootstrap.py seed \
  --credentials "$HOME/nico-private/credentials.yaml"
```

These are three nonempty strings. The BMC site account is `root`. UEFI entries
use an empty username. These are NICo site credentials, not Ubuntu SSH passwords.

| Input | Vault KV v2 path under `secrets/` |
| --- | --- |
| `bmcRootPassword` | `machines/bmc/site/root` |
| `hostUEFIPassword` | `machines/all_hosts/site_default/uefi-metadata-items/auth` |
| `dpuUEFIPassword` | `machines/all_dpus/site_default/uefi-metadata-items/auth` |

Seeding overwrites those three entries. It does not validate hardware login,
change a BMC password directly, or register a machine. Existing factory/device
credentials and expected-machine inventory must be configured through NICo's
release-matched onboarding workflow before ingestion.

## 3. Vault recovery

`vault-init` writes five unseal shares and the root token to the recovery file;
three shares are required. It unseals three pods and creates bootstrap Secrets.
Rerunning with the same file preserves SSH/web passwords and does not reinitialize
an initialized Vault. Back up recovery material securely outside Git.

This lab bootstrap retains a Vault root token in `nico-system/nico-vault-token`
for the PKI configuration Job. Production must replace that bootstrap pattern
with an audited, least-privilege procedure and a tested recovery/unseal design.
Do not delete the token while expecting the existing PKI hook to run again.

Vault and Kubernetes TLS are verified. CLI secret payloads are supplied through
stdin; Kubernetes audit policy and cluster administrators still control access
to stored Secrets. Enable encryption at rest and restrict RBAC in production.
