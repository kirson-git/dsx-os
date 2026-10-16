# DSX OS deployment examples

| Directory | Purpose |
| --- | --- |
| [DPF](DPF/README.md) | Standalone DPF 26.4.0, prerequisites, and Europe/Asia tenants |
| [NICo](NICo/README.md) | NICo + DPF integration; planned, not installable yet |

**Architecture:** external Argo CD is the shared deployment layer. Keep DPF and
NICo entry files separate; standalone DPF must work without NICo. Each installed
resource has one owner. A later NICo integration must define which provisioning
resources NICo owns before replacing the standalone examples.

**Start here: [DPF installation — Step 1, Step 2, Step 3](DPF/README.md#step-1--external-argo-cd-and-dpf-platform).**

The customer file to edit is **[DPF/config.yaml](DPF/config.yaml)**.
It contains our lab API/VIPs and marks editable values with `# please change here`.
Argo reads the Helm templates from Git and uses your local settings.
Optional DHCP and MAC reservations are in the same file; real lab MACs stay local.
This file configures the operator and tenants after the platform is installed;
HBN and hardware provisioning follow separately.

[Simple DPF diagram](DPF/README.md#how-it-fits-together) ·
[Where DHCP is needed](DPF/README.md#where-dhcp-is-needed) ·
[All separate YAML steps](DPF/STAGED-INSTALL.md) ·
[Passwords outside Git](DPF/CREDENTIALS.md) ·
[Persistent agent rules](AGENTS.md)
