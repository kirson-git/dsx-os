# tenant-a: one tenant, one DPU, HBN with VXLAN

These 15 files install one tenant named `tenant-a`: its cluster, the HBN
service with VXLAN, and one DPU. They hold **example values**. They were
generated from the [two-tenant example](../profiles/two-tenant-hbn/README.md)
by [`make-tenant-a.py`](../make-tenant-a.py).

Guided walkthrough:
[dpf-only-workbench.html](../user-documentation/dpf-only-workbench.html).
Download it and open it in a browser.

## Steps

Run every command from the `DPF/` folder.

1. Edit the values at the top of `make-tenant-a.py`, then run it. It rewrites
   this folder with your values.

   ```bash
   python3 make-tenant-a.py
   ```

2. Install the platform: use the [installer](../installer/README.md) or the
   Argo CD steps in the [main guide](../README.md).

3. Store the BMC password: step 5 of the [installer guide](../installer/README.md).

4. Apply the folders in this order. Check each result before the next.

   ```bash
   kubectl apply -f tenant-a/10-operator/
   kubectl apply -f tenant-a/20-cluster/
   kubectl apply -f tenant-a/30-hbn/
   kubectl apply -f tenant-a/40-hardware/
   ```

   The last command can reinstall the DPU. The example keeps `hold: true`, so
   DPF waits for your go-ahead first.

## Which files carry site values

| File | Values |
| --- | --- |
| `10-operator/operatorconfig.yaml` | management API address |
| `20-cluster/dpucluster.yaml` | VIP, interface, VRRP router id |
| `30-hbn/hbn-config.yaml` | VRF, L3 VNI, BGP AS number |
| `30-hbn/ipam-host.yaml`, `30-hbn/ipam-loopback.yaml` | the two address pools |
| `40-hardware/dpudevice.yaml` | BMC address, serial number, part number |
| `40-hardware/dpuflavor.yaml` | DNS server |
| `40-hardware/dpudeployment.yaml` | BMC address selector |

The switch must carry the same VRF and VNI and exchange routes with the AS
number of the DPU. The walkthrough shows the Cumulus commands.

## Status

Generated and checked as valid YAML on 2026-11-11. This one-tenant form has not
been applied to a cluster yet.
