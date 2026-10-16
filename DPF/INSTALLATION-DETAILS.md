# Standalone DPF with external Argo CD

Install external Argo with standard Helm, configure your site and private
credentials, then choose **one YAML** or **separate stage YAMLs**.
Both options use the same underlying platform and profile manifests.

This guide starts with operational Kubernetes after the previous stack and its
CRDs have been removed. It does not perform cleanup, install host Ubuntu or
configure the physical fabric. A full clean rebuild remains unqualified.

## 1. Install external Argo with Helm

With Helm installed and kubectl configured for the management cluster, run from
any directory. These commands use the [official Argo Helm repository](https://argoproj.github.io/argo-helm/)
and the chart version pinned by this package:

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update argo
helm install external-argo-cd argo/argo-cd \
  --version 9.4.1 \
  --namespace argocd --create-namespace \
  --set configs.cm.installationID=dsx-platform \
  --wait --timeout 10m
```

Check the installation before continuing:

```bash
helm status external-argo-cd -n argocd
kubectl get pods -n argocd
```

Helm creates the Argo CRDs on this clean cluster: do not add
`--set crds.install=false`. The installation ID distinguishes external Argo from
DPF's separate service Argo. Default Helm scheduling needs schedulable nodes;
a tainted control-plane-only cluster needs reviewed workload/init-hook tolerations.

The default configuration installs external Argo in `argocd` on the same
management cluster as DPF. Its destination is `in-cluster`; cluster registration
is not required. Configure Argo access, authenticate your CLI or use its UI, and
use the public HTTPS repository without Git credentials. Private forks need
[Git credentials](CREDENTIALS.md).
Do not expand external Argo's Application watch scope to `dpf-operator-system`.

### Reuse existing storage

Select storage explicitly in `DPF/site.yaml`. The fresh-install example enables
Local Path; disable it to reuse a healthy existing provisioner. Before choosing,
inspect both the class and its controller:

```bash
kubectl get storageclass
kubectl get deployments,pods -A | grep local-path
```

If your cluster has another working StorageClass, set `storage.className` in
`DPF/site.yaml`. Only for a lab without a provisioner, set
`storage.installLocalPath: true` and `storage.className: local-path`.
[Regenerate and commit the manifests](#maintainer-option-re-render-after-changing-chart-settings) before syncing.
The offline renderer does not detect cluster storage automatically. Never replace
an existing StorageClass's immutable provisioner field.

Applications use server-side apply with `ClientSideApplyMigration=false`.
CRDs also carry `ServerSideApply=true` individually, avoiding oversized
`last-applied-configuration` annotations when syncing through kubectl.

## 2. Set the DPU BMC IP and create the password Secret

```bash
git clone https://github.com/kirson-git/dsx-os.git
cd dsx-os
```

**DPU IP: edit YAML. Password: run Bash. Never commit the password.**

### DPU BMC IP

Edit these files under `DPF/profiles/two-tenant-hbn/desired/40-provisioning/`:

| DPU | YAML to edit |
| --- | --- |
| Europe | `dpudevice-example-europe.yaml` |
| Asia | `dpudevice-example-asia.yaml` |

Set `spec.bmcIp` to the DPU's **BMC/Redfish address**, not its Ubuntu SSH address.
Set the `provisioning.dpu.nvidia.com/dpudevice-bmc-ip` label to the same address.
Keep the matching BMC-IP selector in `dpuset-hbn-europe.yaml` or
`dpudeployment-hbn-asia.yaml` consistent with it.

### BMC password

On a clean DPF management cluster, create the namespace and run the helper:

```bash
kubectl create namespace dpf-operator-system
bash DPF/credentials.sh
```

Skip namespace creation if it already exists. Type the shared **BMC password**
at the hidden prompt. The helper creates Kubernetes Secret
`dpf-operator-system/bmc-shared-password`; it does not change a Linux login.
No password YAML is needed. See [private-file input](CREDENTIALS.md) if preferred.

**Site prerequisite:** changing only the BMC IP and password is sufficient only
when the rest of the profile already matches your site. The clean Git examples
also contain placeholder management API addresses, tenant VIPs, hardware serials
and network settings. Replace those using [CONFIGURATION.md](CONFIGURATION.md)
before the first deployment; they are not discovered by the password script.

Commit and push the non-secret YAML changes. Argo reads Git, not local edits.
If using a fork, update the repository/revision in the chosen Application YAML.
Private repositories also need [Argo Git access](CREDENTIALS.md).

## Option A: one YAML for the complete stack

```bash
kubectl apply -f DPF/install.yaml
```

This creates one Application named `dpf`. Automatic sync installs prerequisites,
DPF, operator configuration, tenant control planes, HBN definitions and the
provisioning resources. **After you configure real hardware, applying this file
can initiate BFB installation/reprovisioning.** Prepare fabric and a maintenance
window first. It does not automatically execute the external reboot method or
release held node effects.

Argo combines two sources: the rendered platform and the tenant/HBN profile.
Resource waves order them within the same sync. Readiness Jobs wait for the DPF
operator configuration reconciliation and tenant APIs; a final gate checks that
the BMC password Secret is present and nonempty before hardware resources are
applied. That gate does not test BMC authentication. Failed gates stop later
waves; fix the cause and retry sync in Argo. Pruning and self-heal are disabled.

The bootstrap gate checks `SystemComponentsReconciled`, not overall `Ready`.
Overall readiness can depend on services running on provisioned DPUs, so waiting
for it before provisioning would block a clean installation. Check full readiness
after the DPUs have joined their tenant clusters.

```bash
argocd app get dpf
```

## Option B: separate YAMLs for control of each stage

Apply and sync these in sequence instead of Option A:

```bash
kubectl apply -f DPF/generated/applications/00-platform.yaml
argocd app sync dpf-platform
argocd app wait dpf-platform --sync --health --timeout 900

kubectl apply -f DPF/generated/applications/10-operator-config.yaml
argocd app sync dpf-operator-config

kubectl apply -f DPF/generated/applications/20-tenants.yaml
argocd app sync dpf-tenants

kubectl apply -f DPF/generated/applications/30-hbn.yaml
argocd app sync dpf-hbn

kubectl apply -f DPF/generated/applications/40-provisioning.yaml
argocd app sync dpf-provisioning
```

If the Argo CLI is not installed, request a platform sync through kubectl:

```bash
kubectl -n argocd patch application dpf-platform --type merge \
  -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-platform -w
```

Include the sync options in the operation: a kubectl operation does not inherit
all options from `spec.syncPolicy`. Wait for the operation to succeed and the
Application to become Synced/Healthy before proceeding.

The `argocd app sync` commands wait for their sync operation by default. Proceed
after each succeeds. Provisioning can reimage DPUs; run that last sync in the
intended maintenance window. These Applications use manual sync and no pruning.
The same readiness gates are included in their respective stages. Waves do not
order separate Applications, so keep the command sequence above.

Files below are under `DPF/generated/applications/`:

| Step | YAML | What it manages |
| --- | --- | --- |
| 1 | `00-platform.yaml` | Prerequisites, DPF operator and DPF service Argo |
| 2 | `10-operator-config.yaml` | Site API endpoint, provisioning settings and MTUs |
| 3 | `20-tenants.yaml` | Europe and Asia namespaces and tenant control planes |
| 4 | `30-hbn.yaml` | Interfaces, IPAM, service definitions and Europe chain |
| 5 | `40-provisioning.yaml` | Inventory, BFB/flavors, Europe DPUSet and Asia DPUDeployment |

**Choose one option per installation.** Do not apply both over the same resources;
they use different Argo ownership identities. Changing options on an existing
installation requires an ownership migration. Both omit deletion finalizers;
non-cascading Application deletion leaves resources. The UI can request cascading
deletion and add a finalizer. Review the cascade choice before deleting.

## Included prerequisites and ownership

| Component | Pinned chart |
| --- | --- |
| External platform Argo and DPF service Argo | argo-cd 9.4.1 |
| cert-manager | v1.19.3 |
| Kamaji | 1.2.0 |
| Node Feature Discovery | 0.18.3 |
| Maintenance Operator | 0.3.0 |
| DPF operator | v26.4.0 |
| Local Path Provisioner, optional lab storage | 0.0.34 |

External Argo owns the platform and root profile objects. The DPF service Argo
in `dpf-operator-system` delivers DPF-generated services to tenant clusters.
It reuses the external bootstrap's Argo CRDs on this shared cluster and has its
own installation ID and Application namespace watch scope. Never add generated
DPF children, runtime kubeconfigs or Secret data to either public profile.
See [provenance](SOURCES.txt) and the pinned
[NVIDIA prerequisites](https://networking-docs.nvidia.com/dpf/26.4.0/helm-prerequisites).

## Verify the deployed outcome

On the management cluster:

```bash
kubectl wait -n dpf-operator-system dpfoperatorconfig/dpfoperatorconfig \
  --for=condition=Ready --timeout=600s
kubectl get dpus -A
kubectl get dpuclusters -A
kubectl get dpuservices -n dpf-operator-system
kubectl get applications -n dpf-operator-system
kubectl get pods -n dpf-operator-system
```

Inspect each tenant's HBN workloads, BGP/EVPN, host gateway/DNS/HTTPS, data source
interface and management access. Test both-direction tenant isolation with a
positive control proving the destination is alive. Argo Synced and a failed ping
alone do not establish the full outcome. See the
[profile](profiles/two-tenant-hbn/README.md), [fabric contract](profiles/two-tenant-hbn/FABRIC.md),
[production changes](PRODUCTION.md), [recovery](RECOVERY.md) and
[validation](VALIDATION.md). NICo integration is separate: [NICo/](../NICo/README.md).

For external Argo on another cluster, set `sameCluster: false`, register the DPF
cluster privately, set its `destinationName`, and re-render before applying.
This also installs the service Argo CRDs on the remote DPF cluster. Create BMC
credentials on that DPF cluster, and apply the Application YAML on the external
Argo cluster. Qualify this topology before using it for recovery.

## Maintainer option: re-render after changing chart settings

Requirements: an existing management Kubernetes cluster, Helm, kubectl, Python 3,
PyYAML, and the Argo CLI for the explicit sync commands. The administration machine
must reach the relevant APIs; service Argo must reach the tenant cluster endpoints.

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install PyYAML jsonschema
python3 DPF/tools/external.py --help
```

Edit `DPF/site.yaml`:

- `git.repoURL`, `git.revision`, `git.path`: your reviewed Git source. Pin a commit
  for deployment; branch `main` is only the example default.
- `kubernetesVersion`: actual management cluster version used for Helm rendering.
- `storage.installLocalPath`: defaults to `true` for the fresh lab example.
  Set `false` to reuse an existing provisioner.
- `storage.className`: defaults to `local-path`; must name a working StorageClass
  when reusing storage.
- `externalArgo.namespace`: external controller namespace; default `argocd`.
- `externalArgo.sameCluster`: true for a separate installation on this management
  cluster; false when the external controller runs on another cluster.
- `externalArgo.destinationName`: registered DPF cluster name; `in-cluster`
  for the same-cluster default.
- The two installation IDs: distinct controller resource-tracking identities.
- `argoNamespace`: service Argo namespace; this package requires `dpf-operator-system`.

The default `operator.enabled: false` still installs the operator chart. It omits
DPFOperatorConfig because the profile owns that configuration.
Keep `operator.enabled` and `tenants.enabled` false when using either full-profile
option, to avoid duplicate configuration. The one-file entry point is generated
only with those legacy configuration flags disabled.

Render into a new directory (nonempty output is rejected to prevent accidental overwrite):

```bash
render_dir=$(mktemp -d)
python3 DPF/tools/external.py --config DPF/site.yaml --output "$render_dir/generated"
cp -a "$render_dir/generated/." DPF/generated/
cp "$render_dir/install.yaml" DPF/install.yaml
git diff -- DPF/site.yaml DPF/generated DPF/install.yaml
```

The renderer also writes `install.yaml` beside the output directory. The commands
above copy the generated outputs into the checkout. Review the diff, commit
`DPF/site.yaml`, `DPF/install.yaml` and `DPF/generated/`, and push before syncing.
`DPF/generated/platform/` is the Git
path used by the example Application. Rendering prints each actual Helm template
command and does not contact Kubernetes. `tools/render.py` is an internal inherited
renderer; use `tools/external.py` as this package's entrypoint.
