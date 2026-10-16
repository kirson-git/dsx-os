# Optional DHCP in Kubernetes

Edit **the same [config.yaml](config.yaml)** used for DPF. There is no second
customer configuration file. The chart creates a ConfigMap and one dnsmasq pod
in `dpf-network-system`. It serves explicit MAC reservations only, with no dynamic
pool. The pod uses the selected node's network and does not provide DNS service.

| Value | Behavior |
| --- | --- |
| `install-dhcp: "no"` | Default: omit DHCP resources; use existing infrastructure |
| `install-dhcp: "yes"` | Render the DHCP namespace, ConfigMap and Deployment |

Use quoted strings. The public file has blank MAC fields; enabling DHCP with any
blank MAC fails rendering. Our populated local file is `/tmp/dpf-lab/config.yaml`.
Never commit that file or real lab MAC addresses.

## Settings in that file

- `dhcp.nodeName`: Kubernetes node hostname label; it must reach the DPU
  management VLAN.
- `dhcp.interface`: interface on that node, not on the DPU.
- `dhcp.serverIP`: existing address on that interface. An init container refuses
  startup if absent. The chart does not assign or move host IPs.
- `dhcp.subnet` / `netmask`: IPv4 network and contiguous mask, supported `/8`–`/30`.
- `dhcp.gateway`: router offered to clients; must be a usable address in the subnet.
- `dhcp.reservations`: unique names, unicast MACs and usable reserved IPs in
  that subnet.
  Server, gateway and API/VIP addresses cannot be reservations. Names use lowercase
  letters, digits and hyphens, starting with a letter (maximum 63 characters).
- Per-reservation `gateway: false` suppresses the default route; optional `netmask`
  overrides the client's mask. The Asia host example preserves its existing
  `/24` mask and no default route so host traffic continues through HBN.
- Optional `dhcp.dnsServers: [10.10.10.53, 10.10.10.54]` advertises DNS servers.
  Omission/empty list sends no DNS-server option, matching the lab's existing setup.

Lease time is 30 minutes. Lease state is ephemeral; fixed MAC-to-IP reservations
remain in configuration after restart. Configuration changes restart the pod.
The two container images are pinned by digest. A single pinned node is a lab
availability model, not an HA DHCP deployment.

## Lab cutover — before changing to "yes"

The old service also serves both DPU BMCs, both iDRACs and Asia's Linux management
NIC. Keep all seven local reservations if retiring that service. Do not move only
the two DPU entries and abandon the other clients.

The current DHCP identity is `192.168.0.129` on the administration server's
`enp59s0f0np0`. Kubernetes node `l-ae-1137d-001` has `192.168.0.101/24` on `enp7s0`.
The VMs use corporate DHCP on `enp1s0` for `10.220.175.20`–`.22`;
their `enp7s0` addresses `.101`–`.103` are static. Corporate DHCP is separate
and must remain in place. The existing DPU DHCP subnet is `/25`: starting a
pod on `.101` does not
preserve this setup. The server address needs a deliberate transfer.

1. Validate the populated file, the selected node/interface, image availability,
   UDP 67 availability, and all seven reservations before stopping anything.
2. Stop the old `nico-lab-dhcp` service and transfer `.129` to the selected node.
   Ensure it is owned by exactly one machine. Make the change persistent through
   the machines' existing network configuration; a temporary `ip addr` command
   alone will not survive reboot. Preserve the admin host's other addresses/routes.
3. Set `install-dhcp: "yes"` in your local file, then apply it:

   ```bash
   kubectl apply -f /tmp/dpf-lab/config.yaml
   kubectl -n dpf-network-system wait --for=create deployment/dpf-dhcp \
     --timeout=180s
   kubectl -n dpf-network-system rollout status deployment/dpf-dhcp \
     --timeout=180s
   kubectl -n dpf-network-system logs deployment/dpf-dhcp \
     -c dnsmasq --tail=100 -f
   ```

4. Verify DHCPACKs and unchanged IPs/routes for the actual devices. Pod Ready alone
   does not prove DHCP exchange works. Only then disable the old service at boot.
   If validation fails, stop the new deployment, return `.129` to the original
   host and restart the original service. Avoid simultaneous responders.

No live DHCP cutover has been performed by this package's offline validation.
The existing service remains in place until the above network migration is done.

## Disabling after installation

Pruning is disabled deliberately. Changing `"yes"` to `"no"` omits the resources
but does **not** stop an existing DHCP pod. After replacement DHCP is ready,
stop the old pod explicitly and remove its resources through a reviewed Argo
prune/delete operation. Do not enable automatic pruning for the whole DPF stack
just to remove DHCP.

## NICo uses a different integration

NICo **v2.2.2** runs ISC Kea in `nico-dhcp`, loading NICo's hook library to consult
`nico-api`. Its chart mounts `kea_config.json` from a ConfigMap. This is confirmed
by the release's [deployment template](https://github.com/dsx-ai-factory/infra-controller/blob/v2.2.2/helm/charts/nico-dhcp/templates/deployment.yaml)
and [hook implementation](https://github.com/dsx-ai-factory/infra-controller/blob/v2.2.2/crates/dhcp/src/lib.rs).
NICo also has a separate DHCP server on each managed DPU for its attached host.

The MAC/IP inventory can inform a later NICo migration. This standalone dnsmasq
chart is not a replacement for NICo's Kea hooks or its DPU-local server. Define
subnet/client ownership and retire overlapping DHCP before enabling NICo DHCP.
The NICo installer in this repository remains planned.
