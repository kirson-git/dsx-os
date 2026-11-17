# DPF: install it, then bring up your first DPU

Two parts, run from this folder on the admin host (it has `kubectl` and Helm):

1. **Install DPF and its prerequisites** with the installer.
2. **From scratch, after DPF is installed:** the DPU lab, step by step.

```text
Admin host --kubectl--> Management Kubernetes
  Part 1  ./dpf-install.sh   cert-manager, Kamaji, Argo CD, DPF operator
  Part 2  dpu-lab/           1-dpf-settings -> 2-dpu-cluster -> 3-hbn-network -> 4-dpu-install

Server --- DPU (HBN: BGP/EVPN) ---BGP--- Switch
```

## Learn first

Open the interactive workbench: [docs/dpf-only-workbench-new.html](docs/dpf-only-workbench-new.html).
On GitHub click **Download raw file**, then open the saved file in a browser.
It is one file and needs no internet.

## Part 1: the installer

Every install command has a read-only preview.

```bash
./dpf-install.sh --sanity --prereq          # check the cluster
./dpf-install.sh --sanity --hardware        # check the nodes
./dpf-install.sh --install-prereq --dry-run # preview
./dpf-install.sh --install-prereq           # cert-manager, Kamaji, Argo CD, ...
./dpf-install.sh --install-dpf              # the DPF operator
./dpf-install.sh --verify                   # every row: Installed, Ready, Match
```

Details and a recorded run: [docs/dpf-install-script-run.md](docs/dpf-install-script-run.md).

## Part 2: the DPU lab

Follow [dpu-lab/README.md](dpu-lab/README.md). Edit every line marked
`# please change here` in the YAML files; the comment says where to find the value.

```bash
grep -rn 'please change here' dpu-lab/
```

Save the BMC password as a Secret with `./credentials.sh`
([docs/CREDENTIALS.md](docs/CREDENTIALS.md)). Passwords and real addresses stay
outside Git; keep your edited copies in `dpu-lab/site/`, which Git ignores.

## What is in this folder

| Path | What it is |
| --- | --- |
| `dpf-install.sh`, `installer/` | The installer and its internals |
| `credentials.sh` | Checks the BMC login and saves the Secret |
| `dpu-lab/` | The four numbered YAML folders and the step-by-step guide |
| `docs/` | The workbench page, the installer guide, the credentials guide |
| `argo/` | The other way: Argo CD with `config.yaml`. See [argo/README.md](argo/README.md) |

Use the installer **or** the Argo flow on a cluster, not both.
