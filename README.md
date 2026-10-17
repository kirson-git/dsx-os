# DSX OS deployment examples

| Directory | Purpose |
| --- | --- |
| [DPF](DPF/README.md) | Standalone DPF, prerequisites, two tenants and HBN |
| [NICo](NICo/README.md) | NICo + DPF; planned, not installable yet |

**[Start here: install DPF step by step](DPF/README.md#step-1--get-the-files).**

Edit `DPF/config.yaml` for API, tenant VIP and DHCP settings.
Our populated lab copy is `/tmp/dpf-lab/config.yaml`.
Install Argo, prerequisites/DPF, tenants, HBN and provisioning as separate steps.
HBN and hardware overrides live in separate stage files.
Passwords and real MACs stay outside Git.

External Argo is the deployment layer. Each resource has one owner; do not mix
combined and staged Applications. Standalone DPF does not require NICo.

[Demo commands](DPF/DEMO.txt) · [Passwords](DPF/PASSWORDS.md) ·
[DHCP](DPF/DHCP.md) · [Separate YAML stages](DPF/STAGED-INSTALL.md) ·
[Platform/tenant-only config](DPF/PLATFORM-AND-TENANTS.md) ·
[Agent rules](AGENTS.md)
