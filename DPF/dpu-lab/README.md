# Lab guide: configure one DPU and install its OS

This guide takes one BlueField-3 from "DPF is installed" to "the DPU runs its
OS and has joined the DPU cluster". Follow the steps in order. Do not skip a
check: each step says what you must see before you continue.

- **The addresses, serial numbers and host names in this folder are examples.**
  They stand in for the values of the lab where this guide was run. Put your
  own values into `tenant-europe.conf` and `tenant-asia.conf`, then let
  `new-tenant.sh` write them into the YAML files. `get-values.sh` reads most of
  them for you from the cluster, the DPU BMC and the switch.
- To keep real addresses out of Git, copy the two `.conf` files to
  `dpu-lab/site/` and work on the copies. Git ignores that folder, and the YAML
  is then written there. See [Your values](#your-values).
- Example DPU of the first tenant: serial `MT0000000001`, BMC `192.0.2.246`.
- Every file is explained in [FILES.md](FILES.md). Where each value comes from
  is in [CHECKS.md](CHECKS.md).
- This folder is the single source for the lab: 15 YAML files in four
  numbered folders, two values files, five helper scripts, and this guide. To add a second DPU,
  see [Add one more tenant](#add-one-more-tenant) at the end.
- Guided walkthrough in a browser:
  [dpf-only-workbench.html](../user-documentation/dpf-only-workbench.html).
- All ten steps were run in a lab on 2026-11-14 and 2026-11-15, and the
  output shown is real, with the addresses and serial numbers replaced by the
  examples. The DPU reached `Ready`, both BGP sessions from HBN to
  the switch are up after a fix on the switch (step 9), and the server answers
  through the DPU and reaches the internet (step 10). A second tenant (Asia)
  was added the same day and works the same way.

```text
 0-bmc-secret (optional YAML for step 2)

 Step 1-2     Step 3           Step 4          Step 5          Step 6          Step 7-10
 check +  ->  1-dpf-settings -> 2-dpu-cluster -> 3-hbn-network -> 4-dpu-install -> release hold, install,
 password     (1 file)         (2 files)       (7 files)       (5 files)       reboot, check, server
```

## Before you start

- Run every command from the `dsx-os/DPF/` folder, on the admin host (the host
  that holds this repository and `kubectl`).
- This guide is for **standalone DPF**. Do not use it on a cluster that runs
  NICo: NICo creates its own DPF objects.
- Steps 7 and 8 reinstall the DPU and reboot its host. Make sure nobody is
  using that host.
- The YAML does not create DHCP reservations, the switch configuration
  (VRF `EUROPE`, VNI `100001`, AS `65101`) or the host OS. They must exist.

## Your values

Each tenant has one small values file. The files in Git hold example values;
every line marked `# please change here` needs your value.

1. Read the values from your systems. The helper only reads and prints no
   password. `--bmc` and `--switch` are optional; ssh asks for the switch
   password:

   ```bash
   bash dpu-lab/get-values.sh --bmc 192.0.2.246 --switch cumulus@192.0.2.254
   ```

   | Part of the output | Gives you |
   | --- | --- |
   | 1. Management cluster | `API_IP`, `API_PORT` |
   | 2. DPU card (read from the DPU BMC) | `SERIAL`, `OPN` |
   | 4. Switch | the ports of your DPU, `VRF`, `L3VNI`, `ASN`, and the loopbacks the switch accepts |

   `VIP`, `VRID`, `HOST_NET` and `LOOPBACK` are values you choose with the
   network team. Part 2 needs the BMC password Secret of step 2; until it
   exists, the helper prints a `curl` command instead.

2. Put the values into the values file and write them into the YAML:

   ```bash
   bash dpu-lab/new-tenant.sh dpu-lab/tenant-europe.conf --force
   ```

To keep your real values out of Git, use copies in the ignored folder
`dpu-lab/site/` instead. The YAML is then written next to the copies, and you
apply from there (`dpu-lab/site/1-dpf-settings/` and so on):

```bash
mkdir -p dpu-lab/site
cp dpu-lab/tenant-europe.conf dpu-lab/tenant-asia.conf dpu-lab/site/
bash dpu-lab/new-tenant.sh dpu-lab/site/tenant-europe.conf
```

The lab that produced this guide works that way: its real addresses and serial
numbers exist only in `dpu-lab/site/`, and the files rendered from them are
identical to what runs in the cluster.

## Step 1: check that DPF is installed

```bash
cd dsx-os/DPF
kubectl get nodes
helm list -n dpf-operator-system
kubectl get pods -n dpf-operator-system
```

You must see three `Ready` nodes, the releases `dpf-operator` (v26.4.0),
`kamaji`, `maintenance-operator`, `argo-cd` and `node-feature-discovery` as
`deployed`, and all pods `Running` or `Completed`.

If your lab is different from this one, edit the lines marked
`# please change here` now. This command lists them:

```bash
grep -rn 'please change here' dpu-lab/
```

## Step 2: save the BMC password

DPF reads the DPU BMC password from a Secret named `bmc-shared-password`.
The password never goes into a YAML file.

1. Create a private file outside Git with these two lines, then protect it:

   ```text
   username=root
   password=YOUR_BMC_PASSWORD
   ```

   ```bash
   chmod 600 /path/to/bmc-credentials
   ```

2. Test the login. This saves nothing:

   ```bash
   bash credentials.sh --ip 192.0.2.246 \
     --bmc-pass /path/to/bmc-credentials --insecure-bmc --check-only
   ```

   ```text
   PASS BMC 192.0.2.246: BMC login passed; BlueField identity returned
   Checks passed; no Secret changed.
   ```

3. Run the same command without `--check-only` to save the Secret:

   ```bash
   bash credentials.sh --ip 192.0.2.246 \
     --bmc-pass /path/to/bmc-credentials --insecure-bmc
   ```

   ```text
   Saved Secret dpf-operator-system/bmc-shared-password; value hidden.
   ```

`--insecure-bmc` is needed because the lab BMC uses a self-signed certificate.
More options are in [CREDENTIALS.md](../CREDENTIALS.md).

**Other way: the Secret as a YAML file.** Use this if you want every part of
the install to be a `kubectl apply`. The password is then in a file on disk, so
keep that file private. Git ignores it; only the example file is in Git.

```bash
cp dpu-lab/0-bmc-secret/bmc-secret.yaml.example dpu-lab/0-bmc-secret/bmc-secret.yaml
chmod 600 dpu-lab/0-bmc-secret/bmc-secret.yaml
```

Open `dpu-lab/0-bmc-secret/bmc-secret.yaml` and put the BMC password between
the quotes. Then apply it and prove that the password works:

```bash
kubectl apply -f dpu-lab/0-bmc-secret/
bash dpu-lab/get-values.sh --bmc 192.0.2.246
```

The helper must print the serial number of the DPU. If it prints
`HTTPError 401`, the password in the file is wrong: fix it before you go on,
because repeated wrong logins can lock the BMC account. The YAML passed a
server dry-run in this lab; the real apply was not run, because the Secret
already exists here.

## Step 3: operator configuration

```bash
kubectl apply -f dpu-lab/1-dpf-settings/
kubectl get dpfoperatorconfig -n dpf-operator-system
```

Wait about 30 seconds. Continue when you see:

```text
NAME                READY   PHASE     AGE
dpfoperatorconfig   True    Success   30s
```

New pods appear in `dpf-operator-system`: `dpf-provisioning-controller-manager`,
`dpuservice-controller-manager`, `kamaji-cm-controller-manager`, `bfb-registry`.

## Step 4: DPU cluster

This creates a small Kubernetes control plane for the DPUs, on the floating
address `192.0.2.200`.

```bash
kubectl apply -f dpu-lab/2-dpu-cluster/
kubectl get dpucluster -n dpu-cluster-lab
```

It took about 80 seconds here. Continue when you see:

```text
NAME              READY   PHASE   TYPE     MAXNODES   VERSION   NODESCOUNT   AGE
dpu-cluster-lab   True    Ready   kamaji   1000       v1.34.0   0            81s
```

`NODESCOUNT 0` is correct: no DPU has joined yet.

## Step 5: HBN service

A DPUDeployment must name a service, so this step cannot be skipped.

```bash
kubectl apply -f dpu-lab/3-hbn-network/
kubectl get dpuservicetemplate,dpuserviceinterface,dpuserviceipam -n dpf-operator-system
```

The interfaces and the two IPAM pools show `Pending`. That is expected until a
DPU joins the cluster. Continue.

## Step 6: hardware (DPF stops and waits)

```bash
kubectl apply -f dpu-lab/4-dpu-install/
kubectl get bfb,dpu,dpudeployment,dpunodemaintenance -n dpf-operator-system
```

Wait about one minute. Continue when you see the BFB `Ready` and the DPU in
phase `Node Effect`:

```text
NAME                                                PHASE   AGE
bfb.provisioning.dpu.nvidia.com/bf-bundle-v26.4.0   Ready   46s

NAME                                                    READY   OPERATIONAL   PHASE         AGE
dpu.provisioning.dpu.nvidia.com/dpu-node-lab-lab-dpu1           Unknown       Node Effect   45s
```

`Node Effect` means DPF is holding: `hold: true` in `dpudeployment.yaml` created
the object `dpu-node-lab-hold`. Nothing has been written to the DPU yet.

## Step 7: release the hold (the OS install starts)

Only do this when the DPU and its host are free.

```bash
kubectl annotate dpunodemaintenance dpu-node-lab-hold -n dpf-operator-system \
  --overwrite provisioning.dpu.nvidia.com/wait-for-external-nodeeffect=false
kubectl get dpu -n dpf-operator-system -w
```

The phase changed to `OS Installing` within 15 seconds here. Press `Ctrl-C` to
stop watching. To see the progress:

```bash
kubectl get dpu dpu-node-lab-lab-dpu1 -n dpf-operator-system \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.message}{"\n"}{end}'
```

```text
BFBTransferred=False install task 17% complete
```

The image transfer took 5 minutes and the OS install 17 more
(`BFBTransferred=True`, then `OSInstalled=True`). Ten minutes after that the
phase changed to `Rebooting`: 32 minutes after the hold was released.

The DPU has **not** joined the DPU cluster yet. `NODESCOUNT 1` in
`kubectl get dpucluster` appears early and does not mean a node joined.

## Step 8: power-cycle the host

The DPUNode uses `nodeRebootMethod: external`, so DPF does not reboot the host.
It waits for you. The host is the Dell R750 with iDRAC `192.0.2.241`.

1. Wait until this prints `true`. The DPU phase is then `Rebooting`:

   ```bash
   kubectl get dpunode dpu-node-lab -n dpf-operator-system \
     -o jsonpath='{.metadata.annotations.provisioning\.dpu\.nvidia\.com/dpunode-external-reboot-required}{"\n"}'
   ```

2. Read the host power state. `curl` asks for the iDRAC `root` password:

   ```bash
   R=https://192.0.2.241/redfish/v1/Systems/System.Embedded.1
   curl -sk --user root $R | grep -o '"PowerState":"[A-Za-z]*"'
   ```

   ```text
   "PowerState":"On"
   ```

3. Shut the host down. Repeat the command from point 2 until it shows `Off`
   (10 seconds here):

   ```bash
   curl -sk --user root -X POST -H "Content-Type: application/json" \
     -d '{"ResetType":"GracefulShutdown"}' $R/Actions/ComputerSystem.Reset
   ```

4. Wait 30 seconds, then power the host on:

   ```bash
   curl -sk --user root -X POST -H "Content-Type: application/json" \
     -d '{"ResetType":"On"}' $R/Actions/ComputerSystem.Reset
   ```

5. Wait about 3 minutes, until the DPU answers again:

   ```bash
   ping -c 2 192.0.2.244
   ```

6. Tell DPF the reboot is done:

   ```bash
   kubectl annotate dpunode dpu-node-lab -n dpf-operator-system \
     provisioning.dpu.nvidia.com/dpunode-external-reboot-required-
   kubectl get dpu -n dpf-operator-system -w
   ```

   The phases were `DPU Config`, `DPU Cluster Config` (about 10 minutes),
   `Node Effect Removal`, then `Ready`: 14 minutes in total.

The iDRAC password is not in this guide. Take it from your private records.
If a login fails with HTTP 401, stop after one or two tries so the account
does not lock: in this lab an older tool had changed the password, and the
record with the old one was stale.

## Step 9: final check

```bash
kubectl get dpu,dpudeployment,dpuserviceipam -n dpf-operator-system
```

```text
NAME                                                    READY   OPERATIONAL   PHASE   AGE
dpu.provisioning.dpu.nvidia.com/dpu-node-lab-lab-dpu1   True    True          Ready   115m

NAME                                       READY   PHASE     AGE
dpudeployment.svc.dpu.nvidia.com/hbn-lab   True    Success   115m

NAME                                             READY   PHASE     AGE
dpuserviceipam.svc.dpu.nvidia.com/lab-host       True    Success   124m
dpuserviceipam.svc.dpu.nvidia.com/lab-loopback   True    Success   124m
```

Now look inside the DPU cluster. The admin host cannot reach the cluster
address `192.0.2.200`, so the commands go through a management node
(`198.51.100.22`, port `30437`):

```bash
(umask 077; kubectl -n dpu-cluster-lab get secret dpu-cluster-lab-admin-kubeconfig \
  -o jsonpath='{.data.admin\.conf}' | base64 -d > $HOME/dpu-cluster-lab.kubeconfig)
DPUK="kubectl --kubeconfig $HOME/dpu-cluster-lab.kubeconfig --server https://198.51.100.22:30437 --tls-server-name 192.0.2.200"
$DPUK get nodes
$DPUK -n dpf-operator-system get pods -l app.kubernetes.io/name=hbn
```

```text
NAME                    STATUS   ROLES    AGE     VERSION
dpu-node-lab-lab-dpu1   Ready    <none>   4m17s   v1.34.8

NAME                                      READY   STATUS    RESTARTS   AGE
dpu-cluster-lab-doca-hbn-4zq9v-ds-zwkr7   2/2     Running   0          4m59s
```

The port comes from `kubectl -n dpu-cluster-lab get svc dpu-cluster-lab`.

`Ready` is a control-plane result. It does not prove that traffic flows
through HBN. Check BGP with the helper (part 3 of its output):

```bash
bash dpu-lab/get-values.sh
```

```text
  HBN pod dpu-cluster-lab-doca-hbn-4zq9v-ds-zwkr7:
    local AS number 65101  (bgp_autonomous_system in 3-hbn-network/hbn-config.yaml)
    Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd   PfxSnt Desc
    cumulus(p0_if)  4      65001       891       620        0    0    0 00:04:16            2        3 N/A
    cumulus(p1_if)  4      65001       842       578        0    0    0 00:03:21            2        3 N/A
    RESULT: OK, 2 of 2 BGP sessions to the switch are up.
```

A working session shows a time under `Up/Down` and a number under
`State/PfxRcd`. `Idle` and `never` mean the session is down.

On the first check (2026-11-15) both sessions were `Idle`. The switch still
had the values of an earlier NICo test. Two things were changed on the switch,
and nothing on the DPU:

| On the switch | Before | Now |
| --- | --- | --- |
| `remote-as` of peer group `hbn-europe` (ports `swp19`, `swp20`) | `65120` | `65101` |
| Prefix list `HBN-EU-IN` (inbound, Europe) | NICo addresses only | only `10.60.124.34/32`, the DPU loopback |
| Outbound prefix list of `hbn-europe` | `NICO-PROVISIONING-OUT` | `HBN-UNDERLAY-OUT` |
| Ports `swp21`, `swp22` (the Asia DPU) | NICo peer group, AS `65171` | peer group `hbn-asia`, AS `65201` |

Both Europe sessions came up within two minutes. The switch then learned the
DPU loopback and the route `10.60.126.0/29` in VRF `EUROPE`, and a ping from the
switch to the HBN address `10.60.126.2` worked (3 of 3).

The switch now has the same layout for both lab DPUs:

| | Europe | Asia |
| --- | --- | --- |
| Switch ports | `swp19`, `swp20` | `swp21`, `swp22` |
| Peer group | `hbn-europe` | `hbn-asia` |
| DPU AS (`remote-as`) | `65101` | `65201` |
| VRF / VNI | `EUROPE` / `100001` | `ASIA` / `100002` |
| DPU loopback | `10.60.124.34/32` | `10.60.124.35/32` |
| Route target | `65101:100001` | `65201:100002` |
| State | BGP up | not installed; BGP shows `Connect` |

The step-by-step switch check is in the workbench page, part 5, "Check how the
switch is configured today".

## Step 10: give the server its address

DPF does not configure the server. The server takes the first address of the
host block (`10.60.126.1`), and HBN on the DPU is its gateway (`10.60.126.2`).

1. Open a shell on the server. If the server has a management address, use
   plain `ssh`. In this lab it has none, so the login goes through the HBN pod
   on the DPU. `SERVER_KEY` is the ssh key of the server's `ubuntu` user:

   ```bash
   SERVER_KEY=/path/to/server-key bash dpu-lab/server-login.sh lab
   ```

   The word after the script is the tenant name: `lab` for the Europe server,
   `asia` for the Asia server.

2. On the server, set the address and the gateway on the port that connects to
   the DPU (`enp23s0f0np0` here), then ping the gateway:

   ```bash
   sudo ip addr add 10.60.126.1/29 dev enp23s0f0np0
   sudo ip route add default via 10.60.126.2
   ping -c 3 10.60.126.2
   ```

3. Back on the admin host, check from the other side:

   ```bash
   bash dpu-lab/get-values.sh
   ```

   ```text
       RESULT: OK, 2 of 2 BGP sessions to the switch are up.
       SERVER: OK, the server address 10.60.126.1 answers from HBN (gateway 10.60.126.2, VRF EUROPE).
   ```

A ping from the switch, inside VRF `EUROPE`, to the server `10.60.126.1` also
answered (3 of 3). That path crosses the VXLAN tunnel between switch and DPU.

The two `ip` commands are lost when the server reboots, and they set no DNS
servers. So make the address permanent:

- Copy `server-address.sh` to the server and run it there. It writes one
  netplan file, with the DNS servers, and undoes itself after 3 minutes if the
  gateway does not answer:

  ```bash
  SERVER_KEY=/path/to/server-key bash dpu-lab/server-login.sh lab 'cat > server-address.sh' < dpu-lab/server-address.sh
  SERVER_KEY=/path/to/server-key bash dpu-lab/server-login.sh lab
  ```

  ```bash
  sudo bash server-address.sh enp23s0f0np0 10.60.126.1/29 10.60.126.2 203.0.113.53,203.0.113.54 --check
  sudo bash server-address.sh enp23s0f0np0 10.60.126.1/29 10.60.126.2 203.0.113.53,203.0.113.54
  ```

  The first command only validates. This was run on both lab servers on
  2026-11-15:

  ```text
  Note: an existing netplan file calls this port "dpu-host-pf"; using that name.
  OK: enp23s0f0np0 has 10.60.126.1/29, the gateway 10.60.126.2 answers, and the setting is permanent (/etc/netplan/60-dpu-port.yaml).
  ```

  Afterwards, from each server: the gateway answered 3 of 3, `8.8.8.8` answered
  3 of 3, `cisco.com` resolved, and `https://www.cisco.com` returned HTTP 200.
  A ping from the Europe server to the Asia server got no answer, as expected:
  the tenants are separate. A reboot of a server was not tried.
- Why a script and not a hand-written netplan file: these servers have a
  cloud-init netplan file that claims the same port by its MAC address and
  asks for DHCP. A second file that names the port differently is ignored. The
  script finds the existing name and merges with it.
- DNS servers: `203.0.113.53` and `203.0.113.54` answer from the tenant network.
  `203.0.113.55` and the public DNS `8.8.8.8` do not answer DNS questions there.

## Add one more tenant

A tenant is one DPU cluster, one HBN network (VRF) and one DPU. The four
folders above are the first tenant (Europe in this lab). A second tenant gets
its own copy of the files in folders 2, 3 and 4, with its own names and values.
Folder 1 and the OS image (`bfb.yaml`) are shared.

Each tenant has one small values file, and one script turns it into YAML:

| Values file | Tenant | Its YAML files |
| --- | --- | --- |
| `dpu-lab/tenant-europe.conf` | first tenant, objects named `lab` | the numbered folders 2, 3 and 4 |
| `dpu-lab/tenant-asia.conf` | second tenant, objects named `asia` | `dpu-lab/tenant-asia/`, generated |

For the first tenant the script compares the values file with the numbered
folders. It writes into them only with `--force`:

```bash
bash dpu-lab/new-tenant.sh dpu-lab/tenant-europe.conf
```

```text
Tenant lab is the first tenant: its files are the numbered folders.
OK: all 10 values in tenant-europe.conf match those files. Nothing to do.
```

So a new site needs only these edits: the two values files, and the lines
marked `# please change here` in `1-dpf-settings/operatorconfig.yaml`,
`2-dpu-cluster/dpucluster.yaml` (the interface) and
`4-dpu-install/dpuflavor.yaml` (the DNS servers).

| | First tenant (Europe) | Second tenant (Asia) |
| --- | --- | --- |
| Name in the objects | `lab` | `asia` |
| DPU cluster address (VIP) / VRRP id | `192.0.2.200` / `126` | `192.0.2.203` / `127` |
| DPU BMC / serial | `192.0.2.246` / `MT0000000001` | `192.0.2.249` / `MT0000000002` |
| VRF / VNI / AS | `EUROPE` / `100001` / `65101` | `ASIA` / `100002` / `65201` |
| Host block / loopback | `10.60.126.0/29` / `10.60.124.34/32` | `10.60.127.0/29` / `10.60.124.35/32` |
| Switch ports | `swp19`, `swp20` | `swp21`, `swp22` |

1. Read the serial number and part number of the new DPU from its BMC:

   ```bash
   bash dpu-lab/get-values.sh --bmc 192.0.2.249
   ```

   ```text
     DPU BMC address        192.0.2.249                      -> bmcIp and label dpudevice-bmc-ip
     serial number          MT0000000002                       -> serialNumber and label dpudevice-psid
     part number (OPN)      900-9D3B4-00CV-EA0                 -> opn and label dpudevice-opn
   ```

2. Put the values of the tenant in a values file. `dpu-lab/tenant-asia.conf`
   holds the Asia values of this lab. For another tenant, copy it and edit the
   lines marked `# please change here`.

3. Create the files. The script only writes files; it does not touch the
   cluster. It stops if a value is already used by the first tenant.

   ```bash
   bash dpu-lab/new-tenant.sh dpu-lab/tenant-asia.conf
   ```

   ```text
   Wrote 13 files to .../dpu-lab/tenant-asia/ (2-dpu-cluster, 3-hbn-network, 4-dpu-install)

   Tenant asia: DPU cluster dpu-cluster-asia at 192.0.2.203, VRF ASIA, VNI 100002, AS 65201, DPU MT0000000002.
   ```

4. Check the switch for this tenant (workbench page, part 5). In this lab the
   ports `swp21` and `swp22` already expect AS `65201`, and the switch permits
   the loopback `10.60.124.35/32`.

5. Apply the three folders, then follow steps 7 to 10 of this guide. The
   object names end in `asia`: for example `dpu-node-asia-hold` in step 7 and
   `dpu-node-asia` in step 8. The server of this DPU has the iDRAC
   `192.0.2.243`, and takes the address `10.60.127.1/29` with the gateway
   `10.60.127.2` in step 10.

   ```bash
   kubectl apply -f dpu-lab/tenant-asia/2-dpu-cluster/
   kubectl apply -f dpu-lab/tenant-asia/3-hbn-network/
   kubectl apply -f dpu-lab/tenant-asia/4-dpu-install/
   ```

All five steps were run on 2026-11-15. The times, in UTC:

| Time | What happened |
| --- | --- |
| 10:00 | Folder `2-dpu-cluster` applied; DPU cluster `dpu-cluster-asia` `Ready` after 61 seconds |
| 10:01 | Folders `3-hbn-network` and `4-dpu-install` applied; DPU in `Node Effect` (held) |
| 10:02 | Hold released; `OS Installing` after 11 seconds |
| 10:52 | DPU in `Rebooting`; server `SRV0002` shut down and powered on through its iDRAC |
| 10:55 | DPU answered again; reboot mark removed |
| 11:10 | DPU `Ready`: 68 minutes after the apply |
| 11:12 | HBN pod running; BGP to the switch up, 2 of 2, because the switch was prepared first |
| 11:45 | Server address set with `server-address.sh` (`10.60.127.1/29`, gateway `10.60.127.2`); internet works |

Nothing is open for Asia.

One thing to know: when the Asia server was powered off, the BGP process on
the switch crashed and restarted by itself, and the Europe BGP sessions were
down for about 11 seconds. See [CHECKS.md](CHECKS.md).

## Start again: remove what this guide created

Use this to go back to "DPF is installed, nothing configured", or further to
an empty cluster. **These steps were not run in this lab yet.** They follow the
teardown rules in [RECOVERY.md](../RECOVERY.md): remove the objects in the
reverse order of the install, and wait after each step so DPF can clean up.
Only a server dry-run of the delete commands was done.

Before you start: make sure nobody uses the servers. The DPUs leave their DPU
clusters, so traffic through them stops.

1. Remove the second tenant, last folder first:

   ```bash
   kubectl delete -f dpu-lab/tenant-asia/4-dpu-install/dpudeployment.yaml
   kubectl get dpu -n dpf-operator-system -w
   ```

   Wait until the DPU `dpu-node-asia-asia-dpu1` is gone, then press `Ctrl-C`.

   ```bash
   kubectl delete -f dpu-lab/tenant-asia/4-dpu-install/
   kubectl delete -f dpu-lab/tenant-asia/3-hbn-network/
   kubectl delete -f dpu-lab/tenant-asia/2-dpu-cluster/
   ```

   The deployment goes first on its own, because DPF refuses to delete the
   flavor while a deployment still uses it
   (`DPUFlavor is being referred to by DPUSet`).

2. Remove the first tenant the same way, with the numbered folders:

   ```bash
   kubectl delete -f dpu-lab/4-dpu-install/dpudeployment.yaml
   kubectl get dpu -n dpf-operator-system -w
   ```

   ```bash
   kubectl delete -f dpu-lab/4-dpu-install/
   kubectl delete -f dpu-lab/3-hbn-network/
   kubectl delete -f dpu-lab/2-dpu-cluster/
   ```

3. Remove the DPF settings and, if you want, the BMC Secret:

   ```bash
   kubectl delete -f dpu-lab/1-dpf-settings/
   kubectl delete secret bmc-shared-password -n dpf-operator-system
   ```

   You are now at "DPF is installed": start again at step 2 of this guide.

4. Only for an empty cluster: remove DPF itself with the installer. The first
   command only shows what it would remove:

   ```bash
   ./dpf-install.sh --clean
   ./dpf-install.sh --clean --yes
   ```

What stays as it is: the switch configuration, the address on each server
(`/etc/netplan/60-dpu-port.yaml`), and the OS on the DPU cards until the next
install writes a new one.

If a delete command does not return, do not force it. Look at what the object
waits for, for example with
`kubectl get dpu -n dpf-operator-system -o yaml | grep -A8 conditions`.

## If something goes wrong

| What you see | Cause | What to do |
| --- | --- | --- |
| `namespaces "dpu-cluster-lab" not found` in a dry-run | A dry-run does not create the namespace first | Ignore it; the real apply creates `00-namespace.yaml` first |
| Interfaces and IPAM pools stay `Pending` after step 5 | No DPU has joined yet | Continue; the interfaces turn `Ready` after step 7 and the pools after step 8 |
| The DPU stays in `Node Effect` | The hold is still set | Do step 7. Set the annotation to `false`; do not delete it, DPF adds it back |
| `invalid node effect type: Unknown` in the controller log | `hold` was changed to `false` in the YAML | Put `hold: true` back and use step 7 instead |
| `192.0.2.200` does not answer from the admin host (`no route to host`) | The admin host cannot reach the management nodes on that network; the DPU can | Not a fault. Use the management-node address as in step 9 |
| `node dpu-node-lab-lab-dpu1 not found` in the controller log during `DPU Cluster Config` | The DPU is still starting and has not joined | Wait; it took about 10 minutes here. Much longer means the DPU cannot reach `192.0.2.200`, or its DNS or clock is wrong |
| iDRAC login fails with HTTP 401 | You used an old password file | Stop after one or two tries so the account does not lock. Use the login named in step 8 |
| `hbn-lab` and `hbn-asia` show `Pending` instead of `Success` once a second tenant exists | A status display of DPF v26.4.0 with more than one DPU cluster; it was the same on 2026-10-16 | Not a fault. Judge by `bash dpu-lab/get-values.sh`: BGP up and the server answers |
| BGP neighbors stay `Idle` with `Up/Down` `never` | The switch refuses the session: `bgp_autonomous_system` in `3-hbn-network/hbn-config.yaml` differs from `remote-as` on the switch | On the switch, run `nv config show \| grep -n -B12 remote-as` and make both sides equal. Seen and fixed here on the switch side (step 9) |
| BGP is up but the switch has no route to the DPU loopback | The inbound prefix list on the switch does not permit the loopback | On the switch, add a permit rule for the loopback in `3-hbn-network/ipam-loopback.yaml` |
| The server port stays without an address after `netplan apply` | Another netplan file (cloud-init) claims the port by MAC address and asks for DHCP | Use `server-address.sh` (step 10): it merges with that entry |
| `ping 10.60.126.2` from the server fails | The server port has no address, or it is the wrong port | On the server, `ip -br addr` must show `10.60.126.1/29` on `enp23s0f0np0` (step 10) |
| Warning `Nameserver limits were exceeded` on DPU pods | The DPU has more than three DNS servers in total | Seen here; the pods still run |

To read the controller log (two pods run; only the leader logs the work, so
read both):

```bash
kubectl logs -n dpf-operator-system --prefix --tail=50 \
  -l dpu.nvidia.com/component=dpf-provisioning-controller-manager
```
