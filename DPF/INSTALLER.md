# DPF Bash installer

Install external Argo CD with Helm, then let **one Application** install DPF
prerequisites, DPF, Europe/Asia tenants, HBN and DPU provisioning.
This profile retains the existing Ubuntu hosts, DHCP and fabric configuration.
NICo is a later, separate installation.

## 1. Clone and choose your config

Run on the administration machine with access to the management Kubernetes
cluster. Requires Bash, kubectl, Helm, Python 3 and PyYAML.

```bash
git clone https://github.com/kirson-git/dsx-os.git
cd dsx-os
kubectl get nodes
```

**Our lab:** edit `/tmp/dpf-lab/install.yaml`. It contains the verified lab IPs
and HBN/hardware settings, without passwords. Real MACs stay in this private file.

**Another site:** prepare its single Application using the
[configuration composer](TWO-COMMAND-INSTALL.md#prepare-a-sites-application-once),
then edit that output. The menu requires this four-source, revision-pinned
Application; the older `DPF/config.yaml` and `DPF/install.yaml` are different
workflows and are rejected. Keep the prepared file outside your Git checkout.

## 2. Open the menu

```bash
bash DPF/install.sh --config /tmp/dpf-lab/install.yaml
```

| Choice | Action |
| --- | --- |
| **1** | Show your config and IPs |
| **2** | Install all: external Argo → private passwords → DPF Application |
| **3 / 4 / 5** | Run those three actions separately |
| **6** | Show Kubernetes, Argo, tenant and DPU status |
| **7** | Preview full deletion; read only |
| **8** | Delete DPF, dedicated prerequisites, external Argo and their CRDs |
| **0** | Exit |

For a clean reinstall, choose **7**, then **8**, then **2**. Deletion requires
typing the current kubectl context. It preserves the three management Kubernetes
VMs, Kubernetes networking, host Ubuntu, and external DHCP/router/switch settings.
It destroys tenant Kubernetes state and Kamaji storage. It does not wipe the
physical hosts or DPUs; the following provisioning sync can reimage DPUs and
restart their attached hosts.

Deletion stops on unrelated Argo applications/projects, shared prerequisite
resources, unexpected storage ownership or orphaned platform resources. Restore
the owning Application before retrying an orphaned installation. A controller
or finalizer timeout stops cleanup; the script never force-strips finalizers.
This cleanup is scoped to this two-tenant package, not arbitrary Kubernetes apps.

## 3. Follow Argo

Password prompts are hidden. They ask for the **DPU BMC** password and the shared
**server iDRAC** password, not Ubuntu login passwords. Both are stored in
Kubernetes Secrets outside the Application and Git.
First, a temporary pod validates Redfish credentials and device serials from
your config. Failures stop Secret creation. For our self-signed lab BMCs, add
`--insecure-bmc` to the menu/direct command; trusted certificates are the default.
See [password checks](PASSWORDS.md) for a check-only run and optional OS SSH.

Argo auto-sync continues after the menu exits. Watch it with:

```bash
kubectl -n argocd get application dpf -w
kubectl -n dpf-operator-system get dpus
kubectl get dpuclusters -A
```

The readiness Job checks DPU/tenant/HBN readiness; verify Ubuntu Internet access
and tenant isolation after provisioning. The script has automated tests and
read-only lab checks; a full destructive rebuild must still be tested.

## Direct actions and logs

```bash
# Install external Argo only, using the pinned chart and guide values.
bash DPF/install.sh --action argo

# Install all; prompts for passwords.
bash DPF/install.sh --config /tmp/dpf-lab/install.yaml --action all

# Inspect deletion without changing anything.
bash DPF/install.sh --action delete-plan
```

Other `--action` values are `config`, `passwords`, `dpf`, `status`, `delete` and
`menu` (default). Full deletion always requires an interactive terminal.
Optional `--bmc-password-file PATH` and `--idrac-password-file PATH` avoid the
prompts; files must be outside Git, mode 600/400, with no newline. The iDRAC
username defaults to `root`; use `--idrac-user USER` to change it.

Commands, including Helm install/uninstall, and non-secret output go to the
private `/tmp/dsx-installer.*/installer.log` path printed at startup. Argo runs
DPF resources from Git; its controller/Job logs remain in Kubernetes.

A fresh Argo install creates a new admin password. Retrieve it separately so it
is not written to the installer log:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 --decode
printf '\n'
```

An existing Helm installation keeps its values; the menu does not reset its
admin password. After full deletion, the old password is not retained.
