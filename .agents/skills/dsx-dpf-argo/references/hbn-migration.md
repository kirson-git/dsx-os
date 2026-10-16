# HBN tenant subnet migration

Use this procedure for an authorized HBN data-network change. Preserve
management
SSH, BMC, tenant API VIPs and unrelated cluster networking. Confirm the actual
resource ownership and DPF version; examples below were exercised with DPF 26.4.

## Prepare the complete path

1. Inspect both host netplans, routes, HBN gateways, VRF/VNI/ASN, switch tenant
   routing and the Internet egress router. Record live desired sources and
   current
   health. A tenant API's `nodesCount` is insufficient: query its actual Nodes.
2. For overlapping CIDRs, provide independent routing and connection tracking
   through egress before changing host addresses. Do not install ambiguous
   duplicate
   routes in a shared root routing table. One tested lab design is a network
   namespace
   per tenant, each with its own VLAN transit and SNAT to a distinct veth
   address,
   followed by shared upstream NAT. Preserve anti-spoofing, private-destination
   restrictions, DNS exceptions and established-return filtering. This is a lab
   design, not a mandatory production architecture.
3. Establish persistent interface ownership before moving VLANs from networkd to
   namespaces. Verify that generated netplan VLAN definitions are removed and
   that
   unrelated management addresses, DHCP, Docker and VM networking stay intact.
   Use scoped changes, never a global firewall flush. Check address conflicts
   first.
4. Prepare a timed, scoped rollback. Refuse teardown when required rollback
inputs
   are absent. Honor the user's backup preferences; temporary rollback inputs do
   not
   justify a new cluster backup. If `/run` is `noexec`, invoke rollback scripts
   with their intended interpreter
   (for example, `bash /run/rollback.sh` for Bash) rather than executing them
   directly or changing mount policy.
5. Prove both old tenant prefixes still reach DNS and the Internet through the
new
   egress. Verify management access and persistence, then cancel the
   router-stage
   rollback timer before migrating HBN/hosts. That timer only restores the old
   routing topology; after host cutover it is not a complete rollback by itself.

## Change the owner, then one host

Before rolling HBN, validate the candidate host netplan and prepare coordinated
HBN/host rollback. HBN replacement itself interrupts traffic and can fail before
the host address changes. Arm the host rollback timer immediately before host
apply.

- Create new tenant-scoped DPUServiceIPAM pools for new networks; subnet fields
are
  immutable. Retain original pools while rollback depends on them.
- The optional source overlay is
  `DPF/profiles/two-tenant-hbn/overlapping-subnets`. It adds pools and retains
  the
  base resources. It does not configure host netplan or external routing.
- In the verified lab, the external Argo Application carries private site
Kustomize
  patches. Updating those patches changes its desired state; editing public base
  files alone may be overridden. Render the final combination and server-dry-run
  with the owning field manager before syncing. Never publish private lab
  patches.
- Europe uses a standalone DPUService: change its host-pool reference. Asia uses
a
  DPUDeployment: change its referenced DPUServiceConfiguration, not its
  generated
  DPUService. Keep BFB, flavor and DPU provisioning settings unchanged for a
  subnet
  change. Normal HBN pod replacement interrupts data traffic without
  reinstalling OS.
- Wait for the new HBN gateway and established routing, not just pod `Running`.
  The chart can report ready before FRR finishes applying configuration.
- Change only that host's data address/default gateway in its actual
authoritative
  netplan. Validate a temporary tree, retain scoped rollback input, arm a timer,
  apply, and require fresh management SSH plus gateway/DNS/Internet success
  before
  canceling rollback. Repeat for the second tenant. On failure, coordinate HBN
  pool
  and host rollback; reverting only one leaves mismatched addresses.

## DPF 26.4 service-chain maintenance gate

A DPUDeployment configuration change may generate a new service ID and service
chain. With `serviceChains.upgradePolicy.applyNodeEffect: true` and
`nodeEffect.hold: true`, DPF waits for an external maintenance acknowledgement.
The new HBN pod can remain blocked by the deliberate `invalid-network`
attachment
while the DPU node still selects the previous chain.

Inspect all of the following before acting:

- DPU phase and conditions (`Node Effect` is not an OS-install request).
- DPUNodeMaintenance requestors, `spec.nodeEffect`, and its
  `provisioning.dpu.nvidia.com/wait-for-external-nodeeffect` annotation.
- New DPUService service ID, interface service IDs, old/new service-chain
selectors,
  and the tenant node's `svc.dpu.nvidia.com/dpuservicechain-version` label.
- Confirm the hold belongs to the approved network change and not another
operation.

For that approved maintenance object, the exercised acknowledgement is:

```bash
kubectl -n "$NS" annotate dpunodemaintenance "$MAINTENANCE" \
  provisioning.dpu.nvidia.com/wait-for-external-nodeeffect=false --overwrite
```

Set `NS` and `MAINTENANCE` from the inspected object; do not release all holds.
Observe Node Effect Removal, the new node chain label, cleared network gate,
HBN gateway/routing and eventual DPU Ready/Operational. Do not remove the
`invalid-network` guard by hand or restart the DPU to bypass this dependency.
A separate external-reboot annotation is not the same maintenance mechanism.

## Verify and preserve evidence

Check both real tenant Nodes and HBN containers, gateway address, BGP/EVPN
peers,
VRF/VNI separation, and each host's default route. Bind Internet probes to the
HBN interface and record source IP plus TLS result. Test cross-tenant ICMP and
TCP
in both directions with working destination listener controls. A failed probe
without positive controls is not isolation proof. Check management bypass paths
and IPv6 separately; qualify any untested security boundary.

Record exact commands, timestamps and useful container logs for the simulator.
Keep raw logs private until reviewed; credentials never belong in demo assets.
No background rollback timer may remain armed after an accepted cutover.

DPF 26.4's inspected DPUService summary compares Application count with all
DPUClusters rather than selector-matched clusters. Thus a correctly
single-tenant
HBN Application can be Synced/Healthy while aggregate ApplicationsReady remains
False. Report actual workload/data-path results and the status defect
separately;
do not widen tenant selectors or force status to make the display green.
