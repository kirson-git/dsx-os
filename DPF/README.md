# Install DPF with Argo CD

Use a working Kubernetes cluster with Helm and kubectl. The full walkthrough
uses Git; the site-file workflow below does not. This installs standalone DPF 26.4.0.

## One editable site file — no Git clone

After `dpf-platform` is Synced / Healthy, download
[dpf-site.yaml](dpf-site.yaml). Edit the values marked `EDIT`: management API IP
and port, both tenant VIPs, and the interface on the management nodes.

```bash
curl -fL \
  https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/dpf-site.yaml \
  -o dpf-site.yaml
vi dpf-site.yaml
kubectl apply -f dpf-site.yaml
```

Argo fetches the base manifests from Git and uses the settings in your local file.
No Git push is needed for these IP overrides. Keep your edited file for reuse.
This configures the operator and tenants; passwords, HBN and DPU provisioning
remain separate steps. Reserve tenant VIPs outside DHCP. Do not sync the example
addresses before editing them.

**First, sync DPF configuration:**

```bash
kubectl -n argocd patch application dpf-operator-config --type merge \
  -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-operator-config -w
```

Wait for the sync operation to succeed, then press Ctrl+C to stop watching.
Check its result with:

```bash
kubectl -n argocd get application dpf-operator-config \
  -o jsonpath='{.status.operationState.phase}{"\n"}{.status.operationState.message}{"\n"}'
```

**Then, sync tenants:**

```bash
kubectl -n argocd patch application dpf-tenants --type merge \
  -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-tenants -w
```

These reuse the staged Application names. Do not apply the generic configuration
and tenant Application files afterward; they would remove your overrides.
Do not combine this option with the full-stack `dpf` Application.

For our existing lab, the [lab file](labs/nico-lab/applications.yaml) already
has the saved IPs. If you applied it, start with the first sync command above;
do not replace it with the customer template. [Lab instructions](labs/nico-lab/README.md).

The full walkthrough below also covers prerequisites and later HBN/provisioning.
Skip steps 5–6 there if you used this site-file workflow.

## Before you start

If you cannot push to this repository, fork it on GitHub and replace the clone
URL below with your fork's HTTPS URL.

```bash
git clone https://github.com/kirson-git/dsx-os.git
cd dsx-os
kubectl config current-context
```

If you already cloned the repository, use that checkout.

## 1. Install external Argo with Helm

Skip this step if external Argo CD is already installed.

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update argo
helm install external-argo-cd argo/argo-cd \
  --version 9.4.1 \
  --namespace argocd --create-namespace \
  --set configs.cm.installationID=dsx-platform \
  --wait --timeout 10m
kubectl get pods -n argocd
```

## 2. Choose storage

```bash
kubectl get storageclass
kubectl get deployments,pods -A | grep local-path
```

Edit [DPF/site.yaml](site.yaml):

| Your cluster | `storage.installLocalPath` |
| --- | --- |
| No storage provisioner | `true` — install Local Path |
| Healthy existing provisioner | `false` — reuse `storage.className` |

```yaml
storage:
  installLocalPath: true
  className: local-path
```

The published default is **enabled**. Argo does not detect existing storage.
Disabled means reuse, not uninstall. Do not replace a StorageClass's provisioner.

For a fork or another branch, also set `git.repoURL` and `git.revision` in
`DPF/site.yaml`. Public repositories use HTTPS without credentials;
[private repositories need Git access](CREDENTIALS.md#git-access-for-external-argo).

**If you changed `DPF/site.yaml`, regenerate and push before step 3:**

```bash
python3 -m venv /tmp/dsx-render-venv
/tmp/dsx-render-venv/bin/pip install PyYAML
render_dir=$(mktemp -d)
/tmp/dsx-render-venv/bin/python DPF/tools/external.py \
  --config DPF/site.yaml --output "$render_dir/generated"
cp -a "$render_dir/generated/." DPF/generated/
cp "$render_dir/install.yaml" DPF/install.yaml
git diff -- DPF/site.yaml DPF/generated DPF/install.yaml
git add DPF/site.yaml DPF/generated DPF/install.yaml
git commit -m "Configure DPF site and storage"
git push
```

## 3. Install prerequisites and DPF

Installs cert-manager, optional storage, Kamaji, Node Feature Discovery,
Maintenance Operator, DPF operator and DPF service Argo CD.

<!-- rumdl-disable MD013 -->
```bash
kubectl apply -f DPF/generated/applications/00-platform.yaml
kubectl -n argocd patch application dpf-platform --type merge \
  -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-platform \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OPERATION:.status.operationState.phase -w
```
<!-- rumdl-enable MD013 -->

Wait for **OPERATION = Succeeded, SYNC = Synced, HEALTH = Healthy**.
Press **Ctrl+C** to stop watching; installation keeps running.

### One-liner for unchanged fresh-lab defaults

Use this instead of the apply/sync above. It uses upstream Git with storage enabled.
For customized storage or a fork, use the local YAML command above.

<!-- rumdl-disable MD013 -->
```bash
kubectl apply -f https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/generated/applications/00-platform.yaml && kubectl -n argocd patch application dpf-platform --type merge -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
```
<!-- rumdl-enable MD013 -->

## 4. Set IPs and create the BMC password Secret

Edit these files under `DPF/profiles/two-tenant-hbn/desired/`:

| Setting | Files |
| --- | --- |
| Management API address | `10-operator-config/dpfoperatorconfig-dpfoperatorconfig.yaml` |
| Europe/Asia tenant VIPs | `20-tenants/dpucluster-tenant-*.yaml` |
| DPU BMC IPs, labels and serials | `40-provisioning/dpudevice-example-*.yaml` |
| Matching DPU selectors | `40-provisioning/dpuset-hbn-europe.yaml`, `dpudeployment-hbn-asia.yaml` |
| HBN interfaces and address pools | `30-hbn/` |

[CONFIGURATION.md](CONFIGURATION.md) lists the exact fields. Replace the example
addresses, hardware identities and network settings before continuing.

```bash
bash DPF/credentials.sh
kubectl -n dpf-operator-system get secret bmc-shared-password

git diff -- DPF/profiles/two-tenant-hbn/desired
git add DPF/profiles/two-tenant-hbn/desired
git commit -m "Configure DPF tenants and hardware"
git push
```

The helper prompts for the BMC password privately. Never commit passwords.
Argo reads pushed Git changes, not local edits. Your Applications must point to
the repository and branch receiving these commits (step 2).

## 5. Apply DPF configuration

Sets the management API endpoint and enables DPF controllers.

<!-- rumdl-disable MD013 -->
```bash
kubectl apply -f DPF/generated/applications/10-operator-config.yaml
kubectl -n argocd patch application dpf-operator-config --type merge \
  -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-operator-config \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OPERATION:.status.operationState.phase -w
```
<!-- rumdl-enable MD013 -->

Wait for **OPERATION = Succeeded and SYNC = Synced**, then press Ctrl+C.
The bootstrap job checks controller reconciliation; full DPF readiness comes
later, after provisioning DPUs.

## 6. Create Europe and Asia tenants

Creates both tenant control planes and waits for their Kubernetes APIs.

<!-- rumdl-disable MD013 -->
```bash
kubectl apply -f DPF/generated/applications/20-tenants.yaml
kubectl -n argocd patch application dpf-tenants --type merge \
  -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-tenants \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OPERATION:.status.operationState.phase -w
```
<!-- rumdl-enable MD013 -->

Wait for **OPERATION = Succeeded and SYNC = Synced**, then press Ctrl+C.

## 7. Apply HBN networking

Creates the HBN service definitions, interfaces, address pools and service chain.
HBN runs on the DPUs after provisioning.

<!-- rumdl-disable MD013 -->
```bash
kubectl apply -f DPF/generated/applications/30-hbn.yaml
kubectl -n argocd patch application dpf-hbn --type merge \
  -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-hbn \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OPERATION:.status.operationState.phase -w
```
<!-- rumdl-enable MD013 -->

Wait for **OPERATION = Succeeded and SYNC = Synced**, then press Ctrl+C.

## 8. Provision the DPUs

**This stage can reimage DPUs.** Confirm the device identities, BFB/flavor and
fabric settings. The profile requires external reboot and node-effect handling;
[review these steps](profiles/two-tenant-hbn/README.md) before syncing.

<!-- rumdl-disable MD013 -->
```bash
kubectl apply -f DPF/generated/applications/40-provisioning.yaml
kubectl -n argocd patch application dpf-provisioning --type merge \
  -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-provisioning \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OPERATION:.status.operationState.phase -w
```
<!-- rumdl-enable MD013 -->

Wait for **OPERATION = Succeeded and SYNC = Synced**, then press Ctrl+C.
This means the manifests were applied; DPU installation can still be running.

## 9. Check status

```bash
kubectl -n argocd get applications
kubectl -n dpf-operator-system get pods
kubectl get dpuclusters -A
kubectl get dpus -A -w
```

Check DPU readiness, tenant workloads, HBN networking, Internet access and tenant
isolation using the [validation guide](INSTALLATION-DETAILS.md#verify-the-deployed-outcome).
If a sync fails, stop before the next stage and inspect its error:

```bash
kubectl -n argocd get applications \
  -o custom-columns=NAME:.metadata.name,PHASE:.status.operationState.phase,MESSAGE:.status.operationState.message
```

## Alternative: one YAML for the full stack

For a separate new installation, complete steps 1–2 and configure/push the site
settings from step 4. Create the namespace before running the password helper:

```bash
kubectl create namespace dpf-operator-system
bash DPF/credentials.sh
kubectl apply -f DPF/install.yaml
kubectl -n argocd get application dpf -w
```

Skip namespace creation if it already exists. This option automatically syncs
all stages, including DPU provisioning. **Do not combine it with the five staged
Applications above.**

[Advanced options](INSTALLATION-DETAILS.md) · [Production](PRODUCTION.md)
· [Deletion and recovery](RECOVERY.md) · [LLM skill](../.agents/skills/dsx-dpf-argo/SKILL.md)

Clean rebuild qualification is in progress; this is not a production certification.
