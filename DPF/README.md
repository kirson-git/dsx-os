# Install DPF step by step

**Download [config.yaml][raw-config], edit your settings, then apply each stage.**
Our populated lab copy is `/tmp/dpf-lab/config.yaml`.
`install.yaml` is the separate combined installer; do not use it for these steps.

## How DPF brings a DPU online

```text
Management Kubernetes (3 nodes)
  │
  └─ External Argo CD → prerequisites + DPF                 [Step 3]
       │
       ├─ Create Europe + Asia tenant control planes        [Step 4]
       │    config.yaml → DPUCluster (no DPU workers yet)
       │
       ├─ Store BMC credentials; prepare HBN definitions    [Steps 5–6]
       │
       └─ Register hardware and request provisioning       [Step 7]
            DPUDevice + DPUNode: BMC IP, serial, credentials
            │
            ▼
          DPF installs the selected BFB + DPUFlavor
          DPU OS + bundled DOCA software / firmware settings
            │
            ▼
          Required reboot → DPU joins its selected tenant
            │
            ├─ Europe DPU → HBN containers → Europe network
            └─ Asia DPU   → HBN containers → Asia network
```

**Create the tenant control planes first; DPUs join after provisioning.**
Registering hardware lets DPF identify it; registration alone does not install it.
The selected BFB supplies the DPU OS and its bundled software. Firmware updates
depend on the bundle and provisioning settings; installing DPF alone does not
upgrade every firmware component. HBN runs as containers after the DPU joins.
Step 6 only prepares its definitions. This flow installs the **DPU OS**, not the
server's Ubuntu OS.

See NVIDIA's [provisioning flow][nvidia-provisioning] and
[DPUDeployment reference][nvidia-dpudeployment].

[nvidia-provisioning]: https://networking-docs.nvidia.com/dpf/26.4.0/component-description#provisioning-user-flows
[nvidia-dpudeployment]: https://networking-docs.nvidia.com/dpf/26.4.0/dpudeployment

Requires working Kubernetes, kubectl, Helm, curl and Bash. No Git clone is needed.
Keep the existing lab DHCP,
Ubuntu hosts and switch/router configuration. This guide does not install them.
Use one ownership model: do not run these stages alongside the combined `dpf`
Application or the older `dpf-operator-config` / `dpf-tenants` Applications.

## Step 1 — Prepare your local settings directory

```bash
install -d -m 700 /tmp/dpf-lab /tmp/dpf-lab/scripts
kubectl get nodes
```

Expected: management nodes `Ready`. Run these commands from any directory.
Public files use raw GitHub URLs; files you edit stay local.

## Step 2 — Install external Argo CD

For a new installation:

<!-- rumdl-disable MD013 -->
```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update argo
helm install external-argo-cd argo/argo-cd \
  --version 9.4.1 --namespace argocd --create-namespace \
  --set configs.cm.installationID=dsx-platform \
  -f https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/values/external-argo.yaml \
  --wait --timeout 10m
kubectl -n argocd get pods
```
<!-- rumdl-enable MD013 -->

Already installed? Skip installation; use the
[existing-release update](PLATFORM-AND-TENANTS.md#existing-argo--apply-the-startup-fix-once)
if its CRD readiness settings have not been applied.

## Step 3 — Install prerequisites and DPF

Includes Local Path storage, cert-manager, Kamaji, NFD, Maintenance Operator,
DPF and DPF's separate service Argo. To reuse existing storage, follow the
[storage setting](STAGED-INSTALL.md#2-choose-storage) first.

<!-- rumdl-disable MD013 -->
```bash
kubectl apply -f https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/generated/applications/00-platform.yaml
kubectl -n argocd patch application dpf-platform --type merge \
  -p '{"operation":{"retry":{"limit":5,"backoff":{"duration":"10s","factor":2,"maxDuration":"3m"}},"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-platform \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OPERATION:.status.operationState.phase -w
```
<!-- rumdl-enable MD013 -->

Wait for `Succeeded`, `Synced`, `Healthy`. Ctrl+C stops watching only.
If sync fails, stop and read its message before the next step.

## Step 4 — Edit your settings file and create tenants

**Our lab: edit the existing file.** It already contains the lab settings.

```bash
vi /tmp/dpf-lab/config.yaml
```

**New customer:** download the public template once, then edit it:

<!-- rumdl-disable MD013 -->
```bash
install -d -m 700 /tmp/dpf-lab
test -e /tmp/dpf-lab/config.yaml || \
  curl -fsSL https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/config.yaml \
    -o /tmp/dpf-lab/config.yaml
vi /tmp/dpf-lab/config.yaml
```
<!-- rumdl-enable MD013 -->

Edit `spec.source.helm.valuesObject` — these are the variables Argo passes to Helm:

| Variable | Lab value |
| --- | --- |
| `apiServerIP` | `10.220.175.20` — existing Kubernetes API |
| `vipInterface` | `enp7s0` — tenant VIP interface |
| `europeVIP` | `192.168.0.200` — reserved manually |
| `asiaVIP` | `192.168.0.203` — reserved manually |
| `install-dhcp` | `"no"` — retain existing DHCP |

Existing DHCP runs on `l-ae-1137d`, server IP `192.168.0.129`; it supplies DPU OS
addresses `.244` / `.242`. Tenant VIPs are not DHCP allocations.
[DHCP settings](DHCP.md) explain the optional Kubernetes DHCP installation.

```bash
kubectl apply -f /tmp/dpf-lab/config.yaml
kubectl -n argocd get application dpf-site -w
```

Sync starts automatically. Wait for `Synced`, then Ctrl+C and check:

```bash
kubectl -n argocd get application dpf-site -o jsonpath='{.status.operationState.phase}{"\n"}'
kubectl get dpuclusters -A
```

Expected: `Succeeded`, Europe and Asia tenant clusters `Ready`.
**This completes DPF configuration and tenant creation.**

## Step 5 — Set the DPU BMC password

<!-- rumdl-disable MD013 -->
```bash
install -d -m 700 /tmp/dpf-lab/scripts && \
curl -fsSL https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/credentials.sh \
  -o /tmp/dpf-lab/scripts/credentials.sh && \
  bash /tmp/dpf-lab/scripts/credentials.sh
kubectl -n dpf-operator-system get secret bmc-shared-password
```
<!-- rumdl-enable MD013 -->

Enter the shared BMC password at the hidden prompt. It stays outside Git.
This saves the Secret; it does not test connectivity or change the DPU OS password.
iDRAC credentials are not used by these manually controlled stages.

## Step 6 — Prepare HBN definitions

`config.yaml` covers DPF/tenant/DHCP settings. HBN and hardware have separate
stage files. [Public HBN Application (raw)][raw-hbn].
**For our lab**, use the reviewed local overrides below; the public example does
not contain them:

<!-- rumdl-disable MD013 -->
```bash
kubectl apply -f /tmp/dpf-lab/30-hbn-application.yaml
kubectl -n argocd patch application dpf-hbn --type merge \
  -p '{"operation":{"retry":{"limit":5,"backoff":{"duration":"10s","factor":2,"maxDuration":"3m"}},"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-hbn \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OPERATION:.status.operationState.phase -w
```
<!-- rumdl-enable MD013 -->

Wait for `Succeeded` / `Synced`, then Ctrl+C. HBN pods run after DPU provisioning.
For a new site, prepare the [HBN and hardware settings](CONFIGURATION.md) first;
these private lab files are not available from a public raw URL.

## Step 7 — Register and provision DPUs, then check status

[Public provisioning Application (raw)][raw-provisioning]. Our lab uses the local
file below with its hardware settings; do not replace it with the public example.

**Can reimage DPUs.** Our staged profile retains `nodeEffect.hold: true` and
external reboot handling. It can pause for manual maintenance/reboot; applying
this file alone does not guarantee a completed reinstall.

<!-- rumdl-disable MD013 -->
```bash
kubectl apply -f /tmp/dpf-lab/40-provisioning-application.yaml
kubectl -n argocd patch application dpf-provisioning --type merge \
  -p '{"operation":{"retry":{"limit":5,"backoff":{"duration":"10s","factor":2,"maxDuration":"3m"}},"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-provisioning \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OPERATION:.status.operationState.phase -w
```
<!-- rumdl-enable MD013 -->

`Succeeded` / `Synced` means manifests were applied. Ctrl+C, then check hardware:

```bash
kubectl -n dpf-operator-system get dpus -w
```

If a DPU pauses, inspect its conditions before releasing holds or rebooting:

```bash
kubectl -n dpf-operator-system describe dpus
```

Both DPUs must reach `Ready`. Then use the [demo checks](DEMO.txt) for HBN,
Ubuntu Internet access and tenant isolation. The host addresses remain
Europe `10.0.0.2/24` and Asia `10.0.0.1/24` in the existing lab.

[Public stage templates](STAGED-INSTALL.md) · [Hardware settings](CONFIGURATION.md) ·
[Production settings](PRODUCTION.md) · [Deletion and recovery](RECOVERY.md)

[raw-config]: https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/config.yaml
[raw-hbn]: https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/generated/applications/30-hbn.yaml
[raw-provisioning]: https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/generated/applications/40-provisioning.yaml
