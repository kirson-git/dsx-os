# DSX OS deployment examples

| Directory | Purpose |
| --- | --- |
| [DPF](DPF/README.md) | Standalone DPF: installer, DPU lab, HBN network |
| [NICo](NICo/README.md) | NICo Core 2.2.2 + DPF; staged GitOps lab-validation profile |

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
  Part 1  Platform     ./dpf-install.sh   cert-manager, Kamaji, Argo CD, DPF operator
  Part 2  DPU lab      dpu-lab/           one tenant, four numbered folders:
          1-dpf-settings    operator settings
          2-dpu-cluster     the DPU Kubernetes cluster
          3-hbn-network     VRF + L3 VNI + BGP AS number
          4-dpu-install     OS image on the DPU, then host power cycle

Server --- DPU (HBN: BGP/EVPN) ---BGP--- Switch --- fabric
```

## Part 1: install DPF and its prerequisites with the installer

Run from the `DPF/` folder. Every install command has a read-only preview.

```bash
cd DPF
./dpf-install.sh --sanity --prereq          # check the cluster
./dpf-install.sh --sanity --hardware        # check the nodes
./dpf-install.sh --install-prereq --dry-run # preview
./dpf-install.sh --install-prereq           # cert-manager, Kamaji, Argo CD, ...
./dpf-install.sh --install-dpf              # the DPF operator
./dpf-install.sh --verify                   # every row: Installed, Ready, Match
```

Details and a recorded run: [installer guide](DPF/user-documentation/dpf-install-script-run.md).

## Part 2: from scratch, after DPF is installed: the DPU lab

Follow **[DPF/dpu-lab/README.md](DPF/dpu-lab/README.md)** step by step. Every
line marked `# please change here` in the YAML files is a value you set for
your site, and the comments next to it say where to find the value. List them
all with:

```bash
cd DPF
grep -rn 'please change here' dpu-lab/
```

HBN and hardware settings live in the numbered folders. Passwords and real
addresses stay outside Git: save the BMC password with `DPF/credentials.sh`
and keep your edited copies in `DPF/dpu-lab/site/`, which Git ignores.

## Other ways and references

- **Argo CD flow** (settings in `DPF/config.yaml`, applied as Argo
  Applications): [DPF/README.md](DPF/README.md). Use it **or** the installer
  above on a cluster, not both. Each resource has one owner.
- [Demo commands](DPF/docs/DEMO.txt) · [Credentials](DPF/docs/CREDENTIALS.md) ·
  [DHCP](DPF/docs/DHCP.md) · [Separate YAML stages](DPF/docs/STAGED-INSTALL.md) ·
  [Platform/tenant-only config](DPF/docs/PLATFORM-AND-TENANTS.md) ·
  [Agent rules](AGENTS.md)
- Standalone DPF does not require NICo.
