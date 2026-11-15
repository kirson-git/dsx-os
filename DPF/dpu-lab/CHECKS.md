# Where each value comes from

The addresses, serial numbers and host names here are the examples used in the
whole folder. They stand in for the real values of the lab, one for one. The
real ones are kept locally in `dpu-lab/site/`, which Git ignores.

| Value | File | Evidence | State |
| --- | --- | --- | --- |
| API `198.51.100.20:6443` | 1-dpf-settings | `kubectl get nodes -o wide` (first management node) | live |
| `dpuDetector.disable: true`, `installViaRedfish`, `osInstallTimeout 45m` | 1-dpf-settings | two-tenant example profile; same fields as the earlier lab install | inherited |
| DPUCluster VIP `192.0.2.200` | 2-dpu-cluster | `lab/config.yaml` europeVIP | recorded, not re-probed |
| VIP interface `enp7s0` | 2-dpu-cluster | private lab records | recorded, not re-probed |
| `virtualRouterID: 126` | 2-dpu-cluster | Europe tenant in two-tenant-hbn profile | recorded |
| Required fields and `services` for DPUDeployment | all | installed CRDs (`kubectl get crd`) | live |
| BMC `192.0.2.246`, serial `MT0000000001`, OPN `900-9D3B4-00CV-EA0` | 4-dpu-install | `lab/40-provisioning-application.yaml`; BMC `/redfish/v1/Systems/Bluefield` returns the same `SerialNumber` and `PartNumber` | live 2026-11-15 |
| Label `dpudevice-psid` = serial number | 4-dpu-install | Live `DPUDevice` status reports `psid: MT0000000001`, and DPF sets the same label itself | live |
| BFB URL (v26.4.0, Ubuntu 24.04) | 4-dpu-install | same file | live: the BFB became Ready and was installed |
| Flavor DNS `203.0.113.53, 203.0.113.54, 203.0.113.55` | 4-dpu-install | same file (Europe flavor) | live: the DPU pulled its images; warning `Nameserver limits were exceeded` seen |
| VRF `EUROPE`, VNI `100001`, AS `65101` | 3-hbn-network | private lab records; live switch: VRF `EUROPE` VNI `100001` `Up`, route target `65101:100001`, `remote-as 65101` on `swp19`/`swp20` | live 2026-11-15, after the switch fix below |
| Host pool `10.60.126.0/29`, loopback `10.60.124.34/32` | 3-hbn-network | `lab/3-hbn-network-application.yaml`; the switch learned both routes from the DPU | live 2026-11-15 |

## Not verified

- A reboot of a server: the address is written to netplan on both servers, but no server was rebooted afterwards
  to prove that it comes back.
- DNS server `203.0.113.55` (third entry in the DPU flavor) does not answer DNS questions from the tenant network;
  neither does the public `8.8.8.8`. `203.0.113.53` and `203.0.113.54` answer.
- The hand-written netplan file in the workbench page (last step) was not applied as such; the script was used.
  The values (address, gateway, MTU 1500, DNS `203.0.113.53` and `203.0.113.54`) are those of the server netplan
  that worked on 2026-10-16, saved in a private backup of that day.
- Traffic from VRF `EUROPE` to the outside. A ping from HBN to the old uplink address `10.60.125.1` got no reply;
  the admin host has no route back to `10.60.126.0/29`.
- `NODESCOUNT` on the DPUCluster showed 1 before any node had joined; do not use it as proof of a join.
- Applied 2026-11-14. Server dry-run passed for all files on 2026-11-14 (DPUCluster checked in a stand-in namespace). BMC `192.0.2.246` answers ping from this host.
- The `sync-wave` annotations are inherited from the Argo examples and are ignored by `kubectl apply`.
- Addresses (VIP, interface, BMC, DNS) were confirmed correct by the lab owner on 2026-11-15.

## Asia tenant, 2026-11-15

- Created with `new-tenant.sh` from `tenant-asia.conf`; the 13 files passed a server dry-run and were applied.
- DPU `MT0000000002` reached `Ready` 68 minutes after the apply (10:00 to 11:10 UTC); the OS install took about
  50 minutes, Europe took 32. The node `dpu-node-asia-asia-dpu1` joined `dpu-cluster-asia` (v1.34.8).
- HBN: local AS `65201`, router id `10.60.124.35`; IPv4 and EVPN sessions to the switch up on both ports. Ping from
  the switch (VRF `ASIA`) to the HBN gateway `10.60.127.2` answered 3 of 3.
- The server of this DPU (`SRV0002`, Ubuntu `server-asia`) got `10.60.127.1/29` with `server-address.sh` and
  reaches the internet through the DPU (see the server section).
- Since the second DPU cluster exists, the DPUDeployments `hbn-lab` and `hbn-asia` show `Pending` (condition
  `DPUServicesReady`; the HBN service reports `ApplicationsReady=False`), although both HBN applications are
  `Synced` and `Healthy` and traffic works. The same was true on 2026-10-16, when two tenants ran and worked: the
  saved export of that day shows both HBN services with `Ready=False` and `ApplicationsReady=False`. So this is
  a status display of DPF v26.4.0 with more than one DPU cluster, not a fault of today. Judge by BGP and ping.

## Server, 2026-11-15

- The server (`SRV0001`, Ubuntu 24.04.5 `server-europe`) had no IPv4 address on its DPU port `enp23s0f0np0`.
  The lab owner set `10.60.126.1/29` and a default route through `10.60.126.2` by hand.
- Result: ping from HBN (VRF `EUROPE`) to `10.60.126.1` 3 of 3; ping from the switch (VRF `EUROPE`) to
  `10.60.126.1` 3 of 3, across the VXLAN tunnel; the lab owner reported the ping from the server as working.
- Login path: SSH through the HBN pod over the IPv6 link-local address of the server port (`server-login.sh <lab|asia>`
  with the ssh key of the server's `ubuntu` user).
- `server-address.sh` was run on both servers (serials `SRV0001` and `SRV0002` confirmed first). The first run on
  the Asia server failed and undid itself: the cloud-init netplan file claims the port by MAC address under the
  name `dpu-host-pf` with DHCP, so a second entry under the port name was ignored. The script now reuses the
  existing name. Second run on Asia and the run on Europe: `OK`.
- From each server afterwards: gateway 3 of 3, `8.8.8.8` 3 of 3, `cisco.com` resolved through `203.0.113.53` and
  `203.0.113.54`, `https://www.cisco.com` HTTP 200. Europe server to Asia server `10.60.127.1`: 0 of 2, as expected
  for separate tenants. The helper reports `SERVER: OK` for both tenants.

## Switch fix, 2026-11-15

- Found: both BGP sessions of HBN were `Idle`. The live switch (`192.0.2.254`, Cumulus Linux 5.16.5) had
  `remote-as 65120` on peer group `hbn-europe` (ports `swp19`, `swp20`) and did not permit `10.60.124.34/32` in
  prefix list `HBN-EU-IN`. Both values came from a NICo test on 2026-10-26. The DPU sends AS `65101`.
- Changed on the switch only (NVUE revision 24, applied with a 10-minute rollback timer, confirmed and saved):
  `remote-as 65101`, and a new rule 30 in `HBN-EU-IN` that permits `10.60.124.34/32`. Nothing was removed.
- Why the switch side: the switch VRF `EUROPE` imports and exports route target `65101:100001`. Changing the DPU
  to `65120` would also have changed its route target.
- Result: both sessions `Established` for IPv4 and EVPN; the switch has `10.60.124.34/32` through both ports and
  `10.60.126.0/29` in VRF `EUROPE`; ping from the switch VRF `EUROPE` to `10.60.126.2` answered 3 of 3.
- Second change the same day (NVUE revision 25, same procedure), to give the switch one clean layout for both lab
  DPUs: `HBN-EU-IN` now has only rule 10 permitting `10.60.124.34/32`; `hbn-europe` sends `HBN-UNDERLAY-OUT` (the
  switch loopback only); ports `swp21`/`swp22` moved from the NICo peer group to `hbn-asia` (`remote-as 65201`,
  `HBN-AS-IN` permits `10.60.124.35/32`). The Europe sessions stayed `Established` and the ping still answered.
- Third change the same day (NVUE revision 26, same procedure): the NICo leftovers were removed. Gone: peer
  group `nico-pepsi`, prefix lists `NICO-PEPSI-IN` and `NICO-PROVISIONING-OUT`, VRFs `NICO-COKE`, `NICO-PEPSI`,
  `NICO-SERVICES`, VLANs 103 to 105 with their interfaces, and an empty route import. All four DPU sessions stayed
  `Established`; pings from the switch to both HBN gateways answered 3 of 3. The DHCP relay group `nico-oob` was
  kept on purpose: the DPUs get their management addresses through it.
- Switch BGP process crash, 2026-11-15 10:52:36 UTC: when the Asia server was powered off for the DPU reboot, the
  links `swp21` and `swp22` went down and `bgpd` on the switch (Cumulus Linux 5.16.5) crashed with a core file.
  The switch restarted it after 5 seconds and the Europe sessions were back about 11 seconds after the crash.
  It did not crash when the links came back, or during the later cleanup. Cause not investigated; whether the
  switch changes of the same day play a part is unknown.
- The before and after configuration of the switch is kept in a private lab record.

## Procedure sources

| Step | Evidence |
| --- | --- |
| Release the hold by setting `wait-for-external-nodeeffect` to `false` | `crates/dpf/src/sdk.rs` (`HOLD_ANNOTATION`, patched to `"false"`); worked live 2026-11-14 |
| Exactly one node effect may be set | Validation rule in the installed `dpus` CRD |
| Clear `dpunode-external-reboot-required` after the host reboot | `dev/k8s/dpf-sim-controller/README.md`; worked live 2026-11-14 (`Rebooted=True`, then `Ready`) |
| Host power-cycle: iDRAC Redfish `GracefulShutdown`, 30 s off, `On` | Same sequence as `lab/idrac-power.py`; worked live 2026-11-14 |
| Reach the DPU cluster API through a management node port with `--tls-server-name` | Worked live 2026-11-15; `192.0.2.200` gives `no route to host` from the admin host |
