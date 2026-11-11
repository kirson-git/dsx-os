# DPF sanity checks

These checks use the Run:ai installer's separate `sanity-check/` layout and
shared installation log format. They test DPF requirements without installing
the operator or provisioning hardware.

```bash
./dpf-install.sh --sanity --help
./dpf-install.sh --sanity --prereq
./dpf-install.sh --sanity --hardware
./dpf-install.sh --sanity --storage --storage-class local-path
./dpf-install.sh --sanity --nics
./dpf-install.sh --sanity --bmc
./dpf-install.sh --sanity --diagnose --more
```

`--sanity` must be the first argument. Select at most one check; omission selects
`--prereq`. Optional `--context NAME` defaults to the current kubeconfig context.
`--storage-class NAME` defaults to `local-path` and is used by prerequisite,
diagnostic and storage checks. Other checks accept but do not use it. `--more`
is valid only for prerequisite and diagnostic checks. Values use separate
arguments, not `--flag=value`. All checks need Bash, Python 3 and kubectl;
prerequisite/diagnostic checks additionally need Helm and PyYAML. NIC inventory
also needs `timeout`. `--help` does not access Kubernetes.

Each invocation records `logs/latest.log` and `logs/latest/`, replacing the latest
pointers while preserving history. A check returns zero only on its implemented
success condition; nonzero means failure, review needed or a read error. Usage
errors return 2. Menu **S** offers prerequisites, hardware and storage; existing
menu **4** and **10** provide NIC inventory and BMC setup.

| Check | What it establishes | Side effects and limits |
| --- | --- | --- |
| Prerequisites | Installed versions and workload readiness, including Kamaji DataStore existence. | Read-only; not an end-to-end DPU tenant-cluster test. |
| Hardware | Each labeled control-plane/master node has at least 8 CPUs and 16 GB capacity, amd64/arm64, Ready=True, and all three pressure conditions False. | Read-only; no labeled control-plane nodes is not a pass. Does not measure free CPU/RAM, physical disk capacity, HA topology or DPU memory. |
| Storage | A new 64Mi RWO PVC binds and its pod successfully writes, reads and removes a test file. | Creates a unique `dpf-sanity-*` namespace/PVC/pod and removes that namespace; waits for its PV deletion. Requires a Delete-reclaim StorageClass and namespace/PVC/pod permissions. Uses only its new volume. Retain classes are rejected before creation. |
| NICs | Hardware-backed host NICs with addresses/subnets. | Temporary node-network diagnostic pods, removed afterward. No network configuration changes. |
| BMC | Selected node/NIC routing and Redfish authentication. | Interactive, temporary node-network pod; saves nonsecret connection settings. Password is neither saved nor logged. Does not prove controller-pod routing or provisioning privileges. |
| Diagnose | Failed pods, pending storage and warning events. | Read-only; historical warnings can outlive the underlying problem. |

The hardware thresholds come from NVIDIA's
[DPF v26.4.0 system prerequisites](https://github.com/NVIDIA/doca-platform/blob/v26.4.0/docs/public/user-guides/zero-trust/prerequisites/system.md).
The storage probe has a 150-second pod deadline and a 180-second polling limit;
each API command has bounded request/process timeouts. Cleanup gets up to 30
seconds for namespace deletion and another 30 seconds for the PV. Cleanup failure
fails the check and requires review; it does not force finalizers or remove an
existing application volume. Storage tests need the pinned probe image to be
pullable. SIGKILL or lost administration-host connectivity can leave probe
resources requiring manual cleanup.

## Which reference checks fit

Reviewed source: [Run:ai sanity checks](https://github.com/runai-professional-services/runai-installer/tree/16b69974b951a0a1d292e8a206f6d262db241bd4/sanity-check).

| Reference category | DPF decision |
| --- | --- |
| Hardware/resources | Adapted to DPF control-plane requirements; GPU availability is not a DPF control-plane gate. |
| Storage | Kept as an explicit scratch-PVC test. A failed write or missing result cannot pass. |
| Kubernetes/prerequisite versions | Kept, using the bundled NVIDIA DPF pins and existing readiness checks. |
| Certificates/ingress | Run:ai endpoint checks omitted. BMC TLS verification belongs to the BMC check; DPF certificate-controller readiness belongs to prerequisites. |
| NGC credentials | No unconditional credential check. Registry authentication should be tested for the actual selected private artifacts when that workflow is added. |
| Run:ai license/API/service checks | Omitted: not DPF requirements. |

VIP reachability, DHCP/PXE, fabric configuration and NICo-specific services are
not covered by these checks. They need their own validated modules; no result
here is presented as proof of full DPF or NICo deployment readiness.
