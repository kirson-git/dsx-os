# DSX OS deployment examples

| Directory | Purpose |
| --- | --- |
| [DPF](DPF/README.md) | Standalone DPF, prerequisites, two tenants and HBN |
| [NICo](NICo/README.md) | NICo Core 2.2.2 + DPF; staged GitOps lab-validation profile |

**[Start here: install DPF step by step](DPF/README.md#step-1--get-the-files).**

## Learn it first: the interactive workbench

One HTML page explains DPU basics, the YAML files and the install steps, with
the lab's real example values (tenant, VRF, VNI, BGP AS). It is a single file
with no internet needed.

**[Open `dpf-only-workbench-new.html`](DPF/user-documentation/dpf-only-workbench-new.html)**
on GitHub, click the **Download raw file** button (arrow icon, top right of the
file view), then double-click the saved file to open it in your browser.
Or, with the repo cloned: `xdg-open DPF/user-documentation/dpf-only-workbench-new.html`
(macOS: `open`).

## How the pieces fit

```text
Admin host --kubectl--> Management Kubernetes (3 nodes)
                           |
  1 Platform     ./dpf-install.sh   cert-manager, Kamaji, Argo CD, DPF operator
  2 Tenant       DPF/config.yaml    operator settings + DPU cluster
  3 HBN network  3-hbn-network      VRF + L3 VNI + BGP AS number
  4 DPU install  4-dpu-install      OS image on the DPU, then host power cycle

Server --- DPU (HBN: BGP/EVPN) ---BGP--- Switch --- fabric
```

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
