# Where to set IPs and passwords

For operator and tenant API settings, edit [config.yaml](config.yaml).
It contains lab IP examples and blank MAC fields; it marks editable values with
`# please change here`. Apply/sync it using the [platform/tenant guide](PLATFORM-AND-TENANTS.md).
For DHCP placement and the difference between VIPs and DPU addresses, see
[where DHCP is needed](PLATFORM-AND-TENANTS.md#where-dhcp-is-needed).

`DPF/install.yaml` selects Git sources and the target cluster. It contains no
passwords and does not assign DPU IPs itself. The site chart bundles the
operator/tenant stages from
`DPF/profiles/two-tenant-hbn/`; it does not deploy hardware stages.
Optional DHCP settings are documented in [DHCP.md](DHCP.md).

## IP settings

Paths below are relative to `DPF/profiles/two-tenant-hbn/desired/`.

| Address | File | Field |
| --- | --- | --- |
| Management Kubernetes API | `10-operator-config/dpfoperatorconfig-dpfoperatorconfig.yaml` | `spec.overrides.kubernetesAPIServerVIP` and `kubernetesAPIServerPort` |
| Europe tenant API VIP | `20-tenants/dpucluster-tenant-europe.yaml` | `spec.clusterEndpoint.keepalived.vip` |
| Asia tenant API VIP | `20-tenants/dpucluster-tenant-asia.yaml` | `spec.clusterEndpoint.keepalived.vip` |
| Europe DPU BMC | `40-provisioning/dpudevice-example-europe.yaml` | `spec.bmcIp` and matching BMC-IP label |
| Asia DPU BMC | `40-provisioning/dpudevice-example-asia.yaml` | `spec.bmcIp` and matching BMC-IP label |
| Host-facing HBN subnets | `30-hbn/dpuserviceipam-europe-host.yaml`, `dpuserviceipam-asia-host.yaml` | `spec.ipv4Network.network`, `prefixSize`, `gatewayIndex` |
| HBN loopback/VTEP pools | `30-hbn/dpuserviceipam-europe-loopback.yaml`, `dpuserviceipam-asia-loopback.yaml` | `spec.ipv4Network.network` and `prefixSize` |

When changing a BMC address, update its selector in Europe's DPUSet or Asia's
DPUDeployment too. Replace example device serials/names, DPUNode references,
tenant labels and HBN hostname patterns consistently. Tenant VIPs must be reserved
outside DHCP. Review interface names, VRRP IDs, MTUs, DNS and fabric settings.

Ubuntu host PF0 addresses, default routes and DNS are in `host/europe/` and
`host/asia/` beside `desired/`. Those netplan files must be applied to the hosts
through host provisioning; Argo does not install them just because they are in Git.

## BMC IP versus DPU Linux IP

DPF reads the BMC IP from `DPUDevice.spec.bmcIp` and uses Redfish to manage
provisioning. It does not guess that address or derive it from the Linux IP.

The DPU Arm OS management/OOB IP is a separate address supplied by its OS network
configuration, commonly DHCP in this lab. Use your management-network DHCP/IPAM
configuration to reserve it. After the DPU joins its tenant Kubernetes cluster,
its node addresses are visible in that cluster. A BMC endpoint, a tenant API VIP,
an HBN VTEP and a DPU SSH address are different things.

## Passwords and usernames

| Credential | Where it belongs |
| --- | --- |
| DPU BMC password for DPF provisioning | Private Secret `dpf-operator-system/bmc-shared-password`, key `password` |
| DPU Arm OS SSH username/password or key | Your OS provisioning/SSH credential store; not the BMC Secret |
| Ubuntu server SSH username/password or key | Host provisioning/SSH credential store |
| External Argo administrator login | Argo's private credential or SSO configuration |
| Git/registry credentials | Private controller/registry secret-management configuration |

Use the Bash helper on the DPF management cluster after the namespace exists:

```bash
bash DPF/credentials.sh --ip 192.168.0.1,192.168.0.2 \
  --bmc-pass /secure/private/bmc-credentials
```

Read [credential-file setup](CREDENTIALS.md) and replace the example BMC IPs.
The helper validates all BMC logins from a pod before saving the Kubernetes
Secret. It does not change a DPU or server Linux login. The pinned DPF Redfish implementation
selects the BMC account according to its supported platform flow; this Secret is
not an arbitrary per-device username/password map. Devices needing different
BMC credentials require a supported design beyond this shared-password example.

See [credential options](CREDENTIALS.md) for private file input, Git deploy keys
and a production secret-manager approach. Commit reviewed non-secret settings,
but keep passwords, private keys and kubeconfigs outside the repository.
