# Supply credentials outside Git

Passwords, private keys and runtime Kubernetes Secrets are not part of this
repository. Secret names and references can be kept in Git; their values stay
in your secret manager or are entered privately on the administration machine.

## DPF BMC password

For the pinned DPF 26.4.0 Zero Trust flow, the management namespace needs an
Opaque Secret named `bmc-shared-password` with the key `password`. DPF consumes
this shared credential during BMC initialization. The Secret is not an Ubuntu
login or a per-DPU username/password inventory. This flow can initialize/change
BMC authentication; verify the supported BMC model and credential state before
provisioning. See the pinned
[DPF HBN instructions](https://github.com/NVIDIA/doca-platform/blob/v26.4.0/docs/public/user-guides/zero-trust/use-cases/hbn/README.md).

After the platform stage, use a private file with **username and password**:

```text
username=root
password=YOUR_BMC_PASSWORD
```

Store it outside Git as `/secure/private/bmc-credentials`; set mode `600` or
`400`. Values are literal: no quotes, comments or shell expansion. Each key must
appear exactly once; empty values, CR and NUL characters are rejected.
A final newline is allowed. DPF's shared BMC Secret uses the `root` account.

```bash
chmod 600 /secure/private/bmc-credentials
bash DPF/credentials.sh --ip 192.168.0.1,192.168.0.2 \
  --bmc-pass /secure/private/bmc-credentials
```

Replace the example IPs with **BMC IPs**, not DPU Ubuntu SSH IPs. Supply 1–32 unique
IPv4 addresses separated by commas without spaces. The script uses the current
Kubernetes cluster and a temporary host-network pod in `dpf-operator-system`.
It checks authenticated Redfish access to each BlueField system. Every check must
pass before it saves `bmc-shared-password`; otherwise the existing Secret stays
unchanged. This checks login and a BlueField identity response, not an expected
serial-number match. The helper pod is deleted on exit.

Requires Bash, Python 3, kubectl, and permission to read the namespace and
create/exec/delete pods and apply the Secret. The namespace must already exist.
The helper image is pinned by digest and must be reachable by the cluster.

- `--node NAME`: place the helper on a management node that reaches the BMCs;
  otherwise Kubernetes schedules it.
- `--insecure-bmc`: disable BMC TLS verification for self-signed labs only.
  TLS verification is enabled by default.
- `--check-only`: test credentials without saving a Secret.
- `--password-file FILE`: legacy password-only format, root account, no newline;
  use instead of `--bmc-pass`. Validation still requires `--ip`.
- `--skip-check`: advanced compatibility path for `bootstrap-credentials.sh`,
  which already validates credentials and serials. Requires a credential file;
  cannot be combined with IPs, SSH options or `--check-only`.

### Optional DPU OS SSH check

Use a separate file, also mode `600`/`400`, for the installed DPU OS:

```text
username=ubuntu
password=YOUR_DPU_OS_PASSWORD
```

Supply its **OS IPs** and previously verified SSH host keys:

```bash
bash DPF/credentials.sh --ip 192.168.0.1,192.168.0.2 \
  --bmc-pass /secure/private/bmc-credentials \
  --dpu-ip 192.168.0.11,192.168.0.12 \
  --dpu-pass /secure/private/dpu-credentials \
  --ssh-known-hosts /secure/private/known_hosts
```

All three SSH options are required together. The check runs `true` after login
and fails on an unknown/changed host key. When SSH checks are requested, they must
also pass before the BMC Secret is saved. DPU SSH credentials are never saved into
that Secret. Omit SSH checks before OS provisioning; this helper does not create
OS accounts, install an OS, test DHCP/IPAM, or reboot anything.

Credentials go to the helper through exec stdin, not command arguments or pod
specifications. Temporary local files are private and removed on exit. The Secret
uses server-side apply without forcing ownership conflicts. No account password
is changed by this helper.

```bash
kubectl -n dpf-operator-system get secret bmc-shared-password
```

## Git access for external Argo

The supplied Applications use the public repository
`https://github.com/kirson-git/dsx-os.git`; no Git credentials are required.
GitHub SSH URLs require authentication even for public repositories.

For a private fork using SSH, use a read-only repository deploy key stored
outside the checkout. Configure
trusted Git host keys in Argo through your administrator's process, then register
the repository with the external Argo CLI session:

```bash
argocd repo add ssh://git@github.com/kirson-git/dsx-os.git \
  --ssh-private-key-path /secure/private/dsx-readonly-key
```

For HTTPS or SSO, add the credentials through your Argo administration process;
do not embed them in `git.repoURL`. External Argo Git credentials and DPF BMC
credentials belong to different controllers and may be on different clusters.

## Registries and production secret managers

For private images/charts, use the pinned DPF
[private registry guide](https://github.com/NVIDIA/doca-platform/blob/v26.4.0/docs/public/advanced-configuration/using-private-registries.md)
and the relevant workload/chart secret references. A Secret existing in the
management namespace does not automatically authorize every tenant workload.
Keep Docker config files, registry tokens and chart credentials outside Git.

A production secret manager can deliver the same required Secret names and keys
using its Kubernetes integration. Commit only approved references to the external
store, with separate controller authentication configured privately. This package
does not install a secret-manager operator or claim provider-specific integration.
Kubernetes Secret data requires cluster RBAC and encryption-at-rest protections;
base64 encoding is not encryption.

Ubuntu host/DPU SSH credentials, external reboot/iDRAC credentials and tenant
kubeconfigs also remain private. Only optional DPU SSH credentials are inputs to
this helper; iDRAC and tenant
kubeconfigs use their separate workflows.

## External Argo initial login

Argo generates its initial administrator password in its own cluster. Retrieve
it privately on the administration terminal when needed; never redirect it into
this repository or shared command logs:

```bash
argocd admin initial-password -n argocd
```

Change the initial credential through Argo's account-management flow or configure
SSO according to your organization. This is separate from the DPF BMC password.
