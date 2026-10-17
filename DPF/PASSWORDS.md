# Passwords: check first, then install

Passwords stay **outside Git**. The script checks them from temporary Kubernetes
pods on the `bootstrap.hosts[].managementNode` nodes in your prepared Application.
It uses authenticated Redfish GETs and checks the configured device serials.
It does not reboot devices or change their passwords.

## 1. Get the scripts

```bash
git clone https://github.com/kirson-git/dsx-os.git
cd dsx-os
```

Requires kubectl access to management Kubernetes, Python 3 with PyYAML, and
permission to create/delete a temporary namespace and host-network helper pods.
The selected nodes need access to the BMC/iDRAC network and the pinned helper
image on Docker Hub. No DPF installation is needed for the check.

## 2. Validate and save passwords

Use your [prepared full-install Application](TWO-COMMAND-INSTALL.md).
For our lab its path is `/tmp/dpf-lab/install.yaml`:

```bash
bash DPF/bootstrap-credentials.sh --config /tmp/dpf-lab/install.yaml --insecure-bmc
```

Enter the **DPU BMC password**, then the **server iDRAC password** at the hidden
prompts. This two-host profile uses one shared DPU BMC password and one shared
iDRAC account (`root` by default; change with `--idrac-user USER`). Its BF3 BMC
account is `root`. These are not Ubuntu SSH passwords.

Each device prints `PASS` or `FAIL`. Any required failure stops before either
permanent Secret is written. The helper namespace/pods are removed afterward.
On success, the script saves `bmc-shared-password` and
`dpf-host-reboot-credentials` in `dpf-operator-system`.
Normal mode requires external Argo CD and the old staged DPF Applications to
have been removed; it does not perform cleanup itself.

`--insecure-bmc` is an explicit opt-out for our self-signed lab BMC certificates.
**Omit it when using trusted certificates.** iDRAC certificate checking follows
each host's `verifyTLS` value in the same Application. Device serial checks still
run when certificate verification is disabled; they do not replace TLS identity
verification.

To check the existing lab without writing permanent Secrets:

```bash
bash DPF/bootstrap-credentials.sh --config /tmp/dpf-lab/install.yaml \
  --insecure-bmc --check-only
```

## 3. Apply your one YAML

```bash
kubectl apply -f /tmp/dpf-lab/install.yaml
kubectl -n argocd get application dpf -w
```

## Saved passwords on our administration machine

These private files already exist locally; they are **not downloaded from Git**:

| File | Purpose |
| --- | --- |
| `/tmp/dpf-lab/private/bmc-password` | DPU BMC password |
| `/tmp/dpf-lab/private/idrac-password` | Server iDRAC password |
| `/tmp/dpf-lab/passowrd-demo` | Private demo credential notes |

Use the saved files instead of prompts:

```bash
bash DPF/bootstrap-credentials.sh \
  --config /tmp/dpf-lab/install.yaml --insecure-bmc \
  --bmc-password-file /tmp/dpf-lab/private/bmc-password \
  --idrac-password-file /tmp/dpf-lab/private/idrac-password
```

Files must be outside the repository, mode `600` or `400`, nonempty, and contain
no newline. The local shortcut is `bash /tmp/dpf-lab/set-passwords.sh`;
append `--check-only` to test the running lab. The Bash menu also runs these
checks before saving its password Secrets.

## Optional DPU Ubuntu SSH check

A clean DPU may not have its OS yet, so SSH is skipped unless requested. To test
an existing OS, include its separate SSH credentials and verified host keys:

```bash
bash DPF/bootstrap-credentials.sh --config /tmp/dpf-lab/install.yaml \
  --insecure-bmc --check-only --ssh-host 192.0.2.10 --ssh-user ubuntu \
  --ssh-password-file /outside/repo/dpu-ssh-password \
  --ssh-known-hosts /outside/repo/verified-known-hosts
```

Replace the example IP and paths. Repeat `--ssh-host` for more DPUs using the
same account. SSH originates from the first configured management node. It uses
password authentication, requires previously verified SSH host keys and runs
only `true`; supplied SSH checks must pass too. Its password is never saved to
the DPF Secrets. This verifies login, not sudo privileges or HBN forwarding.

Redfish validation does **not** test IPMI, IPAM API credentials, DHCP leases or
address availability. No external IPAM endpoint is defined in this profile.
