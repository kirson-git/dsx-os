# Two-tenant HBN example

This is a sanitized model of the working standalone lab, with separate Europe
and Asia tenant control planes and HBN routing domains. The exact private lab
snapshot stays on the administration machine; these addresses, MACs and device
identities must be replaced before hardware sync.

| Setting | Europe | Asia |
| --- | --- | --- |
| Tenant namespace | tenant-europe | tenant-asia |
| VRF | EUROPE | ASIA |
| DPU BGP ASN | 65101 | 65201 |
| L3 VNI | 100001 | 100002 |
| Host PF0 address | 10.60.10.1/29 | 10.60.20.1/29 |
| HBN host gateway | 10.60.10.2 | 10.60.20.2 |
| Provisioning root | DPUSet | DPUDeployment |

The different root types preserve the two working lab deployment styles. DPF
creates Asia's DPUSet, service and chain children. External Argo manages only
the Asia DPUDeployment and its referenced definitions; it must not adopt children.

## Which YAML controls what

| Directory or resource | Effect |
| --- | --- |
| `desired/10-operator-config` | Management API endpoint, Zero Trust provisioning path, MTUs, service Argo namespace |
| `desired/20-tenants` | Tenant namespaces, Kamaji-backed DPUClusters, VIPs and VRRP IDs |
| `desired/30-hbn` | Physical/service interfaces, IPAM pools, HBN chart/configuration, Europe service chain |
| `desired/40-provisioning` BFB | DPU Arm OS bundle download source |
| `desired/40-provisioning` DPUFlavor | DPU mode, firmware settings, hugepages, OVS, DNS and time-sync startup ordering |
| `desired/40-provisioning` inventory | BMC addresses, hardware identity and tenant selection labels |
| `desired/40-provisioning` DPUSet/DPUDeployment | Select physical DPUs and connect OS/flavor, tenant and services |
| `host/europe` and `host/asia` | Ubuntu host PF0/default route/DNS and management return route; not Kubernetes manifests |
| [Fabric contract](FABRIC.md) | Switch EVPN/BGP/VRFs, NAT, return routes and management isolation |

## Required edits

Start with `profile-inputs.yaml`. Replace example serials and device names in
inventory, selectors and HBN hostname patterns together. Replace BMC addresses,
API/VIP addresses, physical interface names, host MACs, IPAM pools, DNS, ASNs,
VNIs and routing as a consistent site design. Re-check all references after
renaming a resource. `EXAMPLEEUROPE`, `EXAMPLEASIA`, `example-europe` and
`example-asia` are placeholders, not detected hardware.

Both flavors request Zero Trust mode. A BFB or flavor change can require
reprovisioning and reboot. This example retains `OnDelete`, `nodeEffect.hold: true`
and `DPUNode.spec.nodeRebootMethod.external`; it does not silently release node
effects or automatically power-cycle servers. Configure BMC authentication
privately using the supported DPF mechanism before onboarding.

Europe's flavor name is normalized in this public example. Its explicit HBN
service and service chain provide networking; the old private lab DPUSet name
contained `passthrough`, which did not describe the final service chain.

## Sync sequence and acceptance

Choose the one-file or separate-stage workflow in the main installation guide.
Both use the same manifests. Global waves order operator configuration, tenant
APIs, HBN and provisioning; read-only Jobs gate readiness and BMC Secret presence.
With one Application these waves form one sync. With separate Applications,
sync each stage in sequence; provisioning is the final explicit sync. Do not
combine the two ownership models on one installation.

The host configuration must be installed on Ubuntu through your provisioning
system, using management-path preservation and a timed rollback. Copying host
netplan into Git does not make Argo apply it to the host. Asia's example retains
its bridge-based management topology; replace interface
names and MACs for each host. Ubuntu installation itself is outside this package.

Validate each host's PF0 gateway, DNS and HTTPS with the host data address as the
source. Check HBN pods, BGP/EVPN, return routes, and fresh management access.
Attempt cross-tenant traffic with a positive control proving the destination is
alive. Extend checks to both directions, TCP, management paths and IPv6 before
claiming complete isolation. A failed ping alone is insufficient.

The saved lab showed a Europe aggregate DPUService Pending condition despite its
selected service Application being Synced/Healthy and HBN/data-path tests passing.
Do not patch controller status or broaden tenant selectors to hide this condition.
Track it separately from the data-path acceptance result.
