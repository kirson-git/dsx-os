# Every file in `dpu-lab/`

Apply order: `1-dpf-settings` → `2-dpu-cluster` → `3-hbn-network` → `4-dpu-install`.
Values marked `# please change here` in the YAML are the site settings.
All objects use API version `v1alpha1`. The `argocd.argoproj.io/sync-wave`
annotations come from the Argo examples; `kubectl apply` ignores them.

## 0-bmc-secret

| File | Object | What it does |
| --- | --- | --- |
| `bmc-secret.yaml.example` | `Secret/bmc-shared-password` | Example of the Secret with the DPU BMC password. It holds no real password. Copy it to `bmc-secret.yaml`, put the password in, and apply the folder. `bmc-secret.yaml` is ignored by Git. This is the YAML alternative to `credentials.sh` (README step 2). |

## 1-dpf-settings

| File | Object | What it does |
| --- | --- | --- |
| `operatorconfig.yaml` | `DPFOperatorConfig/dpfoperatorconfig` | Starts the DPF provisioning, service and Kamaji controllers. Sets the management API address (`kubernetesAPIServerVIP: 198.51.100.20`, port 6443), installs through Redfish with an external reboot, and sets the OS install timeout (45 min). `dpuDetector` is disabled. |

## 2-dpu-cluster

| File | Object | What it does |
| --- | --- | --- |
| `00-namespace.yaml` | `Namespace/dpu-cluster-lab` | Holds the DPU cluster. The `00-` prefix makes it apply before the cluster. |
| `dpucluster.yaml` | `DPUCluster/dpu-cluster-lab` | A Kamaji Kubernetes control plane for the DPUs. Keepalived floats VIP `192.0.2.200` on `enp7s0` (VRRP id 126). The DPU joins this cluster after its OS install. |

## 3-hbn-network

| File | Object | What it does |
| --- | --- | --- |
| `hbn-template.yaml` | `DPUServiceTemplate/doca-hbn-lab` | Which HBN Helm chart and image run on the DPU (`doca-hbn` 3.4.0, 6Gi, 3 SFs). |
| `hbn-config.yaml` | `DPUServiceConfiguration/doca-hbn-lab` | HBN settings: VRF `EUROPE`, L3 VNI `100001`, BGP AS `65101`, unnumbered BGP on p0/p1, and requests the two addresses below. |
| `if-p0.yaml`, `if-p1.yaml` | `DPUServiceInterface/lab-p0`, `lab-p1` | Physical uplink ports p0 and p1. |
| `if-pf0hpf.yaml` | `DPUServiceInterface/lab-pf0hpf` | The host-facing port (PF 0). |
| `ipam-host.yaml` | `DPUServiceIPAM/lab-host` | Host-facing pool `10.60.126.0/29`. |
| `ipam-loopback.yaml` | `DPUServiceIPAM/lab-loopback` | DPU loopback `10.60.124.34/32`. |

The switch must carry the same VRF, VNI and AS number.

## 4-dpu-install

| File | Object | What it does |
| --- | --- | --- |
| `bfb.yaml` | `BFB/bf-bundle-v26.4.0` | The OS image: BlueField bundle 3.4.0 (Ubuntu 24.04, 64k pages), downloaded into the BFB registry. |
| `dpuflavor.yaml` | `DPUFlavor/hbn-lab-v26.4.0` | How the DPU is configured: zero-trust mode, firmware and OS update flags, NVConfig (46 VFs, 20 SFs), hugepages, grub arguments, OVS setup and DPU DNS (`203.0.113.53`, `203.0.113.54`, `203.0.113.55`). |
| `dpudevice.yaml` | `DPUDevice/lab-dpu1` | The physical DPU: BMC `192.0.2.246`, serial `MT0000000001`, OPN `900-9D3B4-00CV-EA0`. |
| `dpunode.yaml` | `DPUNode/dpu-node-lab` | The host that contains the DPU; reboot method `external` (you or an operator power-cycles the host). |
| `dpudeployment.yaml` | `DPUDeployment/hbn-lab` | Ties it together: BFB + flavor + HBN service chains for p0, p1 and pf0hpf. `nodeEffect.hold: true` makes DPF wait before touching the DPU. |

## Values files and helpers

The values in this folder are **examples**. Every line marked
`# please change here` needs your value. A comment that says "same value as ..."
marks a value that appears in more than one file; all copies must match.
`grep -rn 'please change here' dpu-lab/` lists every one of them.

`site/` is where your real values belong. Git ignores it. Copy the numbered
folders there with `cp -rn`, edit the copies, and apply from there. A copy of
folders 2 to 4 for a second tenant goes to `tenant-<name>/`, which Git ignores
too (see "Add one more tenant" in the [README](README.md)).

The helper scripts of the first lab run (`get-values.sh`, `new-tenant.sh`,
`server-login.sh`, `server-address.sh`) and the two `tenant-*.conf` files were
removed from this folder. They are in Git history up to commit `7e30924`, for
example `git show 7e30924:DPF/dpu-lab/get-values.sh`.

## Not YAML, but required

- Secret `bmc-shared-password` (key `password`) in `dpf-operator-system`. Created
  with `credentials.sh`; the value is never stored in these files.
- DHCP reservations for the BMC and DPU OOB, the switch VRF/VNI/BGP and the
  host OS are outside DPF.

## Live state, 2026-11-14/15

| Stage | Applied | Result |
| --- | --- | --- |
| 10 | yes | `dpfoperatorconfig` Ready / Success |
| 20 | yes | `dpu-cluster-lab` Ready, 0 nodes |
| 30 | yes | Template, interfaces and both IPAM pools Ready |
| 40 | yes | BFB Ready; DPU `dpu-node-lab-lab-dpu1` Ready; DPUDeployment `hbn-lab` Success |

Timeline (UTC): hold released 2026-11-14 22:44, OS installed 23:06, host power-cycled 23:43,
DPU joined `dpu-cluster-lab` 23:57, `Ready` 2026-11-15 00:01. The HBN pod runs on the DPU.
Both BGP sessions from HBN to the switch are up since the switch fix of 2026-11-15, and the server `10.60.126.1` answers through the DPU (see [CHECKS.md](CHECKS.md)). The server does not reach the outside yet. Step-by-step: [README.md](README.md).
