---
name: dsx-dpf-argo
description: Use when assisting with standalone DPF installation, storage selection, Argo CD sync failures, site configuration, or HBN tenant-network changes in the dsx-os repository. Covers the customer GitOps package; NICo integration is planned separately.
---

# DSX DPF Argo installation

Use this repository's public Git manifests to install prerequisites, DPF and
reviewed tenant/HBN configuration through external Argo CD. Start with the
[short guide](../../../DPF/README.md); load the
[detailed guide](../../../DPF/INSTALLATION-DETAILS.md) only for the relevant phase.
Paths below are relative to the dsx-os repository root.

## Storage decision

Inspect the target cluster's StorageClasses, provisioner workloads and PVCs.
A StorageClass alone does not prove its provisioner is running.

| Observed state | Choice |
| --- | --- |
| Healthy provisioner and suitable StorageClass | `storage.installLocalPath: false`; set `storage.className` |
| Fresh lab without a provisioner or StorageClass | `storage.installLocalPath: true` |
| Class exists but provisioner is absent | Check its provisioner identity and data; repair or complete the explicitly requested clean reset |

The bundled Local Path chart uses `rancher.io/local-path`. Never patch another
StorageClass's immutable provisioner to fit the chart. Enabling storage creates
a deployment and pod from rendered Helm YAML; it does not run `helm install`.
Disabling storage omits it from desired manifests; it is not an uninstall flag.
The renderer is offline and does not automatically inspect cluster storage.

Edit `DPF/site.yaml`, then render to a fresh directory:

```bash
work=$(mktemp -d)
python3 DPF/tools/external.py --config DPF/site.yaml --output "$work/generated"
```

Review and copy `$work/generated/` to `DPF/generated/` and `$work/install.yaml`
to `DPF/install.yaml`. Validate and push the intended changes before syncing.
Do not claim a local edit changes what Argo reads from Git.

## Ownership and credentials

- For the prepared full lab reinstall, follow
  [the two-command guide](../../../DPF/TWO-COMMAND-INSTALL.md). The private
  multi-source `dpf` Application owns the four stages; never combine it with
  the staged Applications. Its Git revision is pinned and its IPs/HBN patches
  come from the reviewed private inputs. `config.yaml` alone still covers only
  operator/tenants/DHCP; do not claim it contains all hardware settings.
- Optional `bootstrap.hosts` uses DPF-native script Jobs for host reboot,
  identity checks and a DPUNode journal to prevent repeated reset requests.
  The combined unattended profile removes maintenance holds but preserves
  `force: false` and `OnDelete`. It does not reboot for aggregate HBN status.
  Keep host OS/DHCP/router/fabric dependencies in place. Never label a clean
  rebuild proven from unit tests or schema dry-runs alone.
- External Argo runs in `argocd`; DPF service Argo runs in
  `dpf-operator-system`. Keep their installation IDs and watch scopes distinct.
- Public Git sources use HTTPS. SSH URLs still require authentication.
- Recommended: `dpf-platform` plus `DPF/config.yaml` (`dpf-site`). Customers
  edit only `config.yaml`; its Helm values configure operator/tenants and optional
  DHCP. Do not combine it with `dpf-operator-config` or `dpf-tenants`.
- Alternatives: the full-stack `DPF/install.yaml` Application **or** the five
  staged Applications in `DPF/generated/applications/`. Ownership must not overlap.
- Real lab MACs stay local; public MAC fields remain blank. DHCP defaults to
  `install-dhcp: "no"`. Before enabling, follow `DPF/DHCP.md`, preserve all existing
  clients, and transfer the server IP without concurrent responders. Corporate
  DHCP for the management VMs is separate and must remain intact.
- `operator.enabled: false` omits the renderer's legacy DPFOperatorConfig;
  it still installs the operator chart. The profile supplies configuration.
- Configure API endpoints, tenant VIPs, BMC IPs/labels, serials, hardware
  selectors and fabric settings using [CONFIGURATION.md](../../../DPF/CONFIGURATION.md).
  BMC IP is not the DPU's Ubuntu SSH IP.
- Use `bash DPF/credentials.sh` for the Kubernetes BMC password Secret.
  Passwords, private keys, kubeconfigs and backups stay outside Git.
- Full provisioning may reimage DPUs. External reboot and held node effects
  need explicit handling; applying platform prerequisites does not complete HBN.

## Diagnose before retrying

Read Application `status.operationState`, failed resource results, events and
pod logs. Separate old errors from the latest operation and report the current
phase accurately. Never infer DPU readiness from Argo Synced alone.

Large CRDs need `ServerSideApply=true`. Argo 3.3.0 supports
`ClientSideApplyMigration=false` to bypass client-side migration. A kubectl
operation must carry both sync options and retry policy; direct kubectl patches
do not copy `spec.syncPolicy.retry`. The short guide has the complete command.
External Argo must load `DPF/values/external-argo.yaml`: its CRD health rule treats
normal establishment as Progressing and preserves name/schema errors. Keep this
Helm-owned setting outside the DPF Application. A failed operation does not resume
automatically when the health setting changes.
Do not solve annotation limits with force replacement or CRD deletion.

A remaining StorageClass/provisioner is shared infrastructure until ownership
is established. Preserve it when reusing storage. For deletion, inspect
Application finalizers and the UI cascade choice: shipped templates omit deletion
finalizers, but UI actions can request cascading deletion. A delete can remove
namespaces and their PVCs. Reclaim policy `Delete` may remove backing data.
Retained Kamaji etcd PVCs require compatible identities/certificates and an
explicit restore-versus-rebuild decision; do not blindly attach them to a new
installation. Follow [RECOVERY.md](../../../DPF/RECOVERY.md).

Stop retrying when the same error persists; gather the missing evidence and
report the specific blocker. This skill adds no permission for teardown or
hardware reprovisioning. Keep build machines out of cluster administration.

## HBN tenant-network changes

For a subnet migration, read [the HBN migration procedure](references/hbn-migration.md).
It covers separate routing/connection tracking for overlapping CIDRs, authoritative
Argo sources, staged host netplan, DPUDeployment maintenance holds, and validation.
Do not infer that an HBN-only subnet change requires a DPU reboot or BFB reinstall.
Keep credentials and real lab MACs out of public skill examples and Git.

## Verify and communicate

Run `python3 -m unittest discover -s DPF/tests` after renderer changes; regenerate
outputs rather than editing generated YAML by hand. Validate changed Markdown
and relative links. Confirm Git's published revision, then check live operation
success, workload readiness and the requested network/DPU outcome separately.

User instructions should be short numbered steps with exact copy-paste commands
and a compact enabled/disabled choice. Link advanced details instead of expanding
the quick guide. Report what was verified and any remaining blocker.
NICo is planned, not installable through this package. A full clean rebuild or
production qualification must not be claimed from offline tests alone.
