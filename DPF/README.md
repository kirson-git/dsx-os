# Install DPF with Argo CD

Use a working Kubernetes cluster with Helm and kubectl access. This example uses
DPF 26.4.0; NICo integration is planned separately. Clean rebuild qualification
is still in progress.

## 1. Install external Argo with Helm

Skip this step if you already installed external Argo CD.

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update argo
helm install external-argo-cd argo/argo-cd \
  --version 9.4.1 \
  --namespace argocd --create-namespace \
  --set configs.cm.installationID=dsx-platform \
  --wait --timeout 10m
```

## 2. Choose storage

| Your cluster | `storage.installLocalPath` | Result |
| --- | --- | --- |
| No storage provisioner | `true` — enabled | Install Local Path (fresh lab default) |
| Healthy existing storage | `false` — disabled | Reuse `storage.className` |

Check **both** the StorageClass and its running provisioner:

```bash
kubectl get storageclass
kubectl get deployments,pods -A | grep local-path
```

The choice is in [site.yaml](site.yaml):

```yaml
storage:
  installLocalPath: true
  className: local-path
```

Changing this file requires [regenerating and pushing the YAMLs](INSTALLATION-DETAILS.md#maintainer-option-re-render-after-changing-chart-settings).
Argo reads the generated YAMLs from Git; it does not auto-detect existing storage.
Disabling storage installation does not uninstall an existing provisioner.
The bundled provisioner uses `rancher.io/local-path`; do not overwrite a class
with a different provisioner. For production, use your reviewed storage backend.

## 3. Install prerequisites and DPF

For a staged install using the unchanged fresh-lab defaults, apply from public Git:

```bash
kubectl apply -f https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/generated/applications/00-platform.yaml
kubectl -n argocd patch application dpf-platform --type merge \
  -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-platform -w
```

If you customized storage or use a fork, replace the first command with
`kubectl apply -f DPF/generated/applications/00-platform.yaml` from your reviewed
checkout. Its repository URL/revision must point to your pushed changes.

This installs cert-manager, optional storage, Kamaji, Node Feature Discovery,
Maintenance Operator, DPF operator and DPF service Argo CD. Argo applies
Helm-rendered YAML; Kubernetes runs the resulting pods.
Wait for **Synced / Healthy** before continuing. No Git credentials, Argo CLI,
Argo login or SSH tunnel are needed for these kubectl commands.

## 4. Configure your site and password

```bash
git clone https://github.com/kirson-git/dsx-os.git
cd dsx-os
bash DPF/credentials.sh
```

The helper prompts privately for the BMC password and stores it in Kubernetes.
It does not reset a Linux password. Never commit credentials.

Edit the example YAMLs in `DPF/profiles/two-tenant-hbn/desired/`:

| What to change | Files |
| --- | --- |
| Management API address | `10-operator-config/dpfoperatorconfig-dpfoperatorconfig.yaml` |
| Tenant VIPs | `20-tenants/dpucluster-tenant-*.yaml` |
| DPU BMC IPs, labels and serials | `40-provisioning/dpudevice-example-*.yaml` |
| Matching hardware selectors | `40-provisioning/dpuset-hbn-europe.yaml`, `dpudeployment-hbn-asia.yaml` |
| HBN/network settings | Follow [CONFIGURATION.md](CONFIGURATION.md) |

Commit and push site changes before syncing. For a fork, also change the
Application repository URL. The example addresses and identities are placeholders.

## 5. Choose one deployment path

| Option | What to use |
| --- | --- |
| Continue step by step | [Remaining four stage Applications](INSTALLATION-DETAILS.md#option-b-separate-yamls-for-control-of-each-stage) |
| One YAML for a new installation | [install.yaml](install.yaml), after [preparing site settings and credentials](INSTALLATION-DETAILS.md#option-a-one-yaml-for-the-complete-stack) |

**Do not apply both options to the same stack.** If you followed step 3, continue
with the staged option. Provisioning can reimage DPUs; configure real hardware
and the required external reboot/node-effect handling before that stage.

[Detailed guide](INSTALLATION-DETAILS.md) · [Passwords and Git access](CREDENTIALS.md)
· [Production changes](PRODUCTION.md) · [Deletion and recovery](RECOVERY.md)
· [LLM skill](../.agents/skills/dsx-dpf-argo/SKILL.md)
