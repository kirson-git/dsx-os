# Standalone DPF with external Argo CD

Install the management prerequisites and DPF operator through an external
platform Argo CD, then add the [two-tenant HBN profile](profiles/two-tenant-hbn/README.md).
DPF's service Argo CD is a separate installation in `dpf-operator-system`.

Installation uses standard Helm first, then the checked-in Argo YAMLs.
The Python renderer is optional tooling for maintainers who change chart settings.
It has not completed a destructive clean-rebuild qualification. It does not
install management Kubernetes, Ubuntu on the hosts, or the physical fabric.

## Included components

| Component | Pinned chart | Purpose |
| --- | --- | --- |
| External platform Argo | argo-cd 9.4.1 | GitOps controller for this stack |
| DPF service Argo | argo-cd 9.4.1 | Deliver DPF-generated services into tenant clusters |
| cert-manager | v1.19.3 | Certificates |
| Kamaji | 1.2.0 | Tenant control planes and etcd |
| Node Feature Discovery | 0.18.3 | Hardware features |
| Maintenance Operator | 0.3.0 | Node maintenance coordination |
| DPF operator | v26.4.0 | Provisioning and DPU service orchestration |
| Local Path Provisioner, optional | 0.0.34 | Lab storage; replace for production |

These are the inherited DPF 26.4.0 package pins. Do not infer that other Argo or
Kubernetes versions are compatible without testing. See [provenance](SOURCES.txt)
and NVIDIA's [prerequisites](https://networking-docs.nvidia.com/dpf/26.4.0/helm-prerequisites).

## 1. Install external Argo with Helm

Select the intended external-Argo cluster in your current kubectl configuration
and confirm its identity. For a separate cluster, do this on the external cluster.
These commands install a NEW controller; do not adopt an existing Helm release.
The cluster needs schedulable nodes. On a tainted control-plane-only cluster,
provide a reviewed Helm values file with matching workload and Redis-init-job
tolerations; the default command does not add tolerations.

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update argo
helm install external-argo-cd argo/argo-cd \
  --version 9.4.1 \
  --namespace argocd --create-namespace \
  --set configs.cm.installationID=dsx-platform \
  --wait --timeout 10m
```

On a cluster that already has Argo CRDs (including the existing DPF lab), add
`--set crds.install=false` to the Helm install command. This reuses the shared
CRDs; preserve their existing owner and do not delete them during DPF cleanup.
Check schema compatibility before reusing a different Argo version.
The new controller watches its own namespace by default. Do not configure it
to watch the DPF service Application namespace.

Use the configured namespace if you changed it. Configure access and authenticate
to this external Argo CLI/UI privately; no login credentials are in this repository.
For an existing external installation, review its namespace watch scope, installation
ID, CRDs and permissions instead of running this Helm command over it.

The default YAMLs target `in-cluster`: external Argo is a separate installation
on the DPF management cluster. No cluster-registration command is needed for this
case. Give external Argo private Git access if required; see [credentials](CREDENTIALS.md).

For external Argo on a **different cluster**, set `sameCluster: false`, use a
registered remote `destinationName`, and re-render before applying. Register that
DPF cluster privately with `argocd cluster add YOUR_CONTEXT --name dpf-management`.
See the official [cluster registration contract](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd_cluster_add/).

## 2. Install prerequisites and DPF from YAML

Clone the repository to get the YAMLs (or use your own reviewed fork):

```bash
git clone git@github.com:kirson-git/dsx-os.git
cd dsx-os
```

On the external-Argo cluster, create the platform Application and sync it:

```bash
kubectl apply -f DPF/generated/applications/00-platform.yaml
argocd app sync dpf-platform
argocd app wait dpf-platform --sync --health --timeout 900
```

This single Application includes cert-manager, optional storage, Kamaji/etcd,
NFD, Maintenance Operator, DPF operator and the separate service Argo. Resource
waves order their installation. Kamaji setup hooks create runtime certificates;
no certificate or password data is committed here.

On a fresh shared cluster, external Argo's Helm bootstrap owns Argo CRDs and
the service chart omits them. When reusing existing CRDs, keep their existing
owner until a deliberate ownership migration is performed. On separate
clusters, the service chart
includes CRDs on the DPF cluster. The controllers have distinct installation IDs
and watch their own Application namespaces. See
[resource tracking](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_tracking/).

## 3. Configure tenants, HBN and hardware

First replace every site/hardware input in the
[profile](profiles/two-tenant-hbn/README.md). The checked-in examples cannot provision
your real hardware unchanged. Commit the reviewed changes before these commands.

```bash
kubectl apply -f DPF/generated/applications/10-operator-config.yaml
argocd app sync dpf-operator-config
kubectl apply -f DPF/generated/applications/20-tenants.yaml
argocd app sync dpf-tenants
```

On the DPF management cluster, check controller and tenant readiness:

```bash
kubectl wait -n dpf-operator-system dpfoperatorconfig/dpfoperatorconfig \
  --for=condition=Ready --timeout=600s
kubectl wait -n tenant-europe dpucluster/tenant-europe \
  --for=jsonpath='{.status.phase}'=Ready --timeout=600s
kubectl wait -n tenant-asia dpucluster/tenant-asia \
  --for=jsonpath='{.status.phase}'=Ready --timeout=600s
```

Then, on the external-Argo cluster:

```bash
kubectl apply -f DPF/generated/applications/30-hbn.yaml
argocd app sync dpf-hbn
```

After [private BMC credential setup](CREDENTIALS.md), fabric readiness and the
hardware maintenance window are
in place, explicitly submit provisioning. This can install a BFB/reimage DPUs:

```bash
kubectl apply -f DPF/generated/applications/40-provisioning.yaml
argocd app sync dpf-provisioning
```

All five Applications use manual sync, no pruning and no deletion finalizer.
Waves inside one Application do not order the separate Applications. Keep the
steps above explicit until the complete workflow is qualified. External reboot
and held node effects still need operator handling; see the profile.

## 4. Verify the restored outcome

On the management cluster:

```bash
kubectl get dpus -A
kubectl get dpuclusters -A
kubectl get dpuservices -n dpf-operator-system
kubectl get applications -n dpf-operator-system
kubectl get pods -n dpf-operator-system
```

These are inventory checks, not complete acceptance. Inspect the generated service
Applications and HBN pods in each tenant, then validate host gateway/DNS/HTTPS,
source interface, BGP/EVPN, return routing and cross-tenant isolation. The
[profile guide](profiles/two-tenant-hbn/README.md) defines these boundaries.

## Cleanup and production

Read [production changes](PRODUCTION.md) and [teardown/recovery](RECOVERY.md).
No blanket cluster deletion command is provided: shared services, persistent
state and hardware lifecycle must be scoped before teardown.

Validation record: [VALIDATION.md](VALIDATION.md). The future NICo integration
is separate: [NICo/](../NICo/README.md).

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
- `storage.installLocalPath` and `storage.className`: lab provisioning or existing
  production StorageClass.
- `externalArgo.namespace`: external controller namespace; default `argocd`.
- `externalArgo.sameCluster`: true for a separate installation on this management
  cluster; false when the external controller runs on another cluster.
- `externalArgo.destinationName`: registered DPF cluster name; `in-cluster`
  for the same-cluster default.
- The two installation IDs: distinct controller resource-tracking identities.
- `argoNamespace`: service Argo namespace; this package requires `dpf-operator-system`.

The default `operator.enabled: false` still installs the operator chart. It omits
DPFOperatorConfig because the separate profile Application owns that configuration.
Keep `operator.enabled` and `tenants.enabled` false when using the profile, to
avoid assigning the same resources to two Applications. If you choose the optional
legacy tenant renderer instead, do not apply the profile's corresponding resources.

Render into a new directory (nonempty output is rejected to prevent accidental overwrite):

```bash
python3 DPF/tools/external.py --config DPF/site.yaml --output /tmp/dsx-rendered
```

Review the result, replace `DPF/generated/` with the reviewed output, and commit
and push your changes before syncing Argo. `DPF/generated/platform/` is the Git
path used by the example Application. Rendering prints each actual Helm template
command and does not contact Kubernetes. `tools/render.py` is an internal inherited
renderer; use `tools/external.py` as this package's entrypoint.
