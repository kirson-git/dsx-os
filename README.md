# DSX OS deployment examples

| Directory | Purpose |
| --- | --- |
| [DPF](DPF/README.md) | Standalone DPF, prerequisites, two tenants and HBN |
| [NICo](NICo/README.md) | NICo + DPF; planned, not installable yet |

**[Start here: install DPF step by step](DPF/README.md#step-1--get-the-installer).**

The prepared lab uses one private Application: `/tmp/dpf-lab/install.yaml`.
It includes IPs, HBN and hardware settings.
Passwords and real MACs stay outside Git.
For another site,
[prepare its Application](DPF/TWO-COMMAND-INSTALL.md#prepare-a-sites-application-once).

External Argo is the deployment layer. Each resource has one owner; do not mix
combined and staged Applications. Standalone DPF does not require NICo.

[Demo commands](DPF/DEMO.txt) · [Passwords](DPF/PASSWORDS.md) ·
[DHCP](DPF/DHCP.md) · [Separate YAML stages](DPF/STAGED-INSTALL.md) ·
[Platform/tenant-only config](DPF/PLATFORM-AND-TENANTS.md) ·
[Agent rules](AGENTS.md)
