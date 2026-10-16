# Configure the NICo lab through Argo CD

Requires `dpf-platform` to be Synced / Healthy. No Git clone is needed.
This file configures the operator and two tenants; HBN/hardware configuration
remains a later step.

| Setting | Value |
| --- | --- |
| Management API | `10.220.175.20:6443` |
| Europe tenant VIP | `192.168.0.200` |
| Asia tenant VIP | `192.168.0.203` |
| Keepalived interface | `enp7s0` |

The VIPs come from the saved lab configuration; reserve them outside DHCP and
check that they are free before syncing. The interface must exist on the selected
management nodes. This file contains no passwords.

## 1. Apply the lab file

```bash
kubectl apply -f https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/labs/nico-lab/applications.yaml
```

It updates `dpf-operator-config` and `dpf-tenants` with inline IP overrides.
It does not start sync automatically. Do not reapply the generic stage
Application YAMLs afterward: those would remove these overrides. Do not combine
this staged setup with the single full-stack `dpf` Application.

## 2. Sync DPF configuration

```bash
kubectl -n argocd patch application dpf-operator-config --type merge \
  -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-operator-config -w
```

Check the sync operation succeeded before continuing:

```bash
kubectl -n argocd get application dpf-operator-config \
  -o jsonpath='{.status.operationState.phase}{"\n"}{.status.operationState.message}{"\n"}'
```

Press Ctrl+C to stop a watch; it does not stop the sync.

## 3. Sync tenants

```bash
kubectl -n argocd patch application dpf-tenants --type merge \
  -p '{"operation":{"sync":{"prune":false,"syncOptions":["ServerSideApply=true","ClientSideApplyMigration=false","FailOnSharedResource=true"],"syncStrategy":{"hook":{}}}}}'
kubectl -n argocd get application dpf-tenants -w
```

Wait for a successful sync, then check:

```bash
kubectl get dpuclusters -A
```

## Another site: download only this file

```bash
curl -fL \
  https://raw.githubusercontent.com/kirson-git/dsx-os/main/DPF/labs/nico-lab/applications.yaml \
  -o dpf-site.yaml
vi dpf-site.yaml
kubectl apply -f dpf-site.yaml
```

Edit the `value:` entries under `spec.source.kustomize.patches`. Then run the
same two sync commands above, in order. These overrides live in the Application;
Argo reads the base YAMLs from Git. No commit is needed to use local overrides.
Keep the edited file for repeat installations. Full GitOps users can commit the
Application to their own configuration repository.

Uses [Argo inline Kustomize patches](https://argo-cd.readthedocs.io/en/release-3.3/user-guide/kustomize/#patches).
