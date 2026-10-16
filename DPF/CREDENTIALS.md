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

Select the DPF management cluster and create `dpf-operator-system` if absent
before the one-file install (or after the separate platform stage). Enter the
password at the hidden prompt:

```bash
kubectl config current-context
bash DPF/credentials.sh
```

Alternatively, supply an existing private file outside the checkout:

```bash
bash DPF/credentials.sh --password-file /secure/private/bmc-password
```

The file must be readable only by its owner (mode 600 or 400), contain the
password with
no trailing newline, and remain outside Git. The Bash helper uses a private
temporary directory outside Git and removes it
on exit. It passes the Secret through kubectl stdin, does not print the value
and does not put it in process arguments. It uses server-side apply without force-conflicts;
another secret manager's ownership conflict must be resolved deliberately.
The helper changes only the Kubernetes Secret; it does not test BMC authentication.

Check existence without displaying the value:

```bash
kubectl get secret bmc-shared-password -n dpf-operator-system
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
kubeconfigs also remain private. They are not inputs to the BMC password helper.

## External Argo initial login

Argo generates its initial administrator password in its own cluster. Retrieve
it privately on the administration terminal when needed; never redirect it into
this repository or shared command logs:

```bash
argocd admin initial-password -n argocd
```

Change the initial credential through Argo's account-management flow or configure
SSO according to your organization. This is separate from the DPF BMC password.
