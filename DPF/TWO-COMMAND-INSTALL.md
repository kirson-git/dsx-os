# Full DPF install in two commands

For a menu that also installs or removes external Argo, use the [Bash installer](INSTALLER.md).

Use this **after the agreed DPF cleanup**, with external Argo CD and management
Kubernetes still running. Keep the Ubuntu hosts, DHCP reservations, switch and
Internet router configuration. This installs DPF prerequisites, operator, tenants,
HBN and DPU provisioning; it does not install Ubuntu on the servers.

The single `dpf` Application replaces the four staged Applications. Do not run
both approaches together. The credential helper rejects the staged Applications
while they still exist. The Application also uses `FailOnSharedResource=true`.

## Our lab: two commands

The administration server has a prepared private Application at
`/tmp/dpf-lab/install.yaml` and a private credential wrapper. These files contain
the lab settings and are not public customer templates.

```bash
bash /tmp/dpf-lab/set-passwords.sh
kubectl apply -f /tmp/dpf-lab/install.yaml
```

Command 1 creates the namespace and BMC/iDRAC Secrets from private files outside
Git. Command 2 starts Argo auto-sync at a pinned Git revision:

```text
Prerequisites → DPF → Europe/Asia tenants → HBN → provision DPUs → readiness check
```

| Setting | Europe | Asia |
| --- | --- | --- |
| Ubuntu data IP, retained on host | `10.0.0.2/24` | `10.0.0.1/24` |
| HBN gateway, separate per tenant | `10.0.0.254` | `10.0.0.254` |
| Tenant API VIP | `192.168.0.200` | `192.168.0.203` |

Existing VRFs, VNIs and isolation remain unchanged. No shared-network demo is
enabled. Data IPs are static Ubuntu settings; DPU management IPs depend on the
preserved DHCP reservations. Tenant VIPs are manually configured.

## Watch installation

```bash
kubectl -n argocd get application dpf -w
kubectl -n dpf-operator-system get dpus
kubectl get dpuclusters -A
kubectl -n dpf-operator-system logs job/dpf-bootstrap-ready -f
```

The readiness Job appears at the final sync wave. It checks DPU Ready and
OperationalReady, tenant nodes and HBN pod readiness. It does not claim that
Ubuntu Internet traffic passed: verify that after installation. A clean rebuild
is only validated after running this complete workflow on the target lab.

## Reboots and passwords

DPF 26.4's `DPUNode.spec.nodeRebootMethod.script` starts a Kubernetes Job when
provisioning requires a supported host reset. The script validates the iDRAC
service tag, observes a graceful shutdown and power-on, and records progress on
the DPUNode so a retried Job cannot send the same reset repeatedly. This restarts
the attached Ubuntu host as well. It never reboots because an Argo/HBN summary
looks unhealthy. Unknown reset methods or ambiguous failures stop for inspection.

The generated unattended profile sets `nodeEffect.hold: false`; `force: false`
and `OnDelete` remain unchanged. This deliberately removes the manual maintenance
acknowledgement from the fresh-install path. It does not change the live staged
profile while this file is being prepared.

Passwords are separate Secrets: `bmc-shared-password` for DPU BMCs and
`dpf-host-reboot-credentials` for the two server iDRACs. The helper accepts one
shared iDRAC account for this two-host profile; different per-host accounts are
not implemented. With an interactive terminal, another site can use:

```bash
bash DPF/bootstrap-credentials.sh
kubectl apply -f /path/to/your/install.yaml
```

Both passwords are hidden prompts. The iDRAC username defaults to `root`; override
with `--idrac-user USER`. Noninteractive input uses `--bmc-password-file PATH`
and `--idrac-password-file PATH`. Each must be a readable regular file outside
the repository, mode `600` or `400`, nonempty and without a newline. Do not put
passwords in the Application or commit them to Git.

## Prepare a site's Application once

Use the existing reviewed platform, site, HBN and hardware Application inputs.
The site file is the same `config.yaml` format used by the staged workflow.
For automatic reboot, add `bootstrap.hosts` inside its `helm.valuesObject`:

```yaml
bootstrap:
  hosts:
    - name: europe # europe or asia; unique, maximum two hosts
      dpuNode: dpu-node-your-europe # exact final DPUNode name
      idracIP: 192.0.2.41 # please change here: server iDRAC, not DPU BMC
      serial: YOUR_SERVICE_TAG # please change here: verified server SerialNumber
      managementNode: your-management-node # please change here: reaches iDRAC
      verifyTLS: true # false only for an explicitly accepted lab certificate
```

Supply a matching entry for each provisioned DPUNode. In our lab, certificate
verification is explicitly disabled for the existing self-signed iDRACs.
HBN and hardware inputs must contain the reviewed Kustomize `/spec` overrides;
the composer preserves those settings rather than guessing site values.

```bash
python3 DPF/tools/combine_install.py \
  --platform DPF/generated/applications/00-platform.yaml \
  --config /path/to/config.yaml \
  --hbn /path/to/30-hbn-application.yaml \
  --provisioning /path/to/40-provisioning-application.yaml \
  --revision FULL_PUBLISHED_40_CHARACTER_COMMIT_SHA \
  --reboot --output /path/to/install.yaml
```

The output must not already exist. The tool writes a mode-600 Application and
does not access the cluster. Without `--reboot`, omit `bootstrap.hosts`; the
original external reboot and maintenance holds remain manual. After composition,
**edit the generated Application for deployment**; changing an old staged input
does not update the generated output. Keep the private output outside public Git.

External Argo must already have the [CRD readiness rule](values/external-argo.yaml)
used by this package. Preserve its CRDs during DPF teardown. Follow the
[recovery boundary](RECOVERY.md) rather than deleting every cluster CRD.
