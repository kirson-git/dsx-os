# Changes required for production

This package is based on a working lab topology and pinned charts. It does not
claim a qualified production installation. Complete these site-specific changes
and validate the result before production use.

| Area | Change or decision |
| --- | --- |
| Compatibility | Validate the selected DPF, Kubernetes, firmware/BFB, HBN and both Argo versions together; use the supported matrix, not a latest-version assumption. |
| External Argo | Choose dedicated management cluster or separate installation; configure schedulable nodes/tolerations (including init hooks), HA, SSO/RBAC, TLS, backups, audit logs and restricted AppProjects/destinations. |
| Service Argo | Keep its namespace/watch scope/installation ID distinct; qualify changes to its DPF-pinned chart. Same-cluster instances share one CRD owner/schema. |
| Git | Use a reviewed repository and immutable release revisions; restrict write access and promotion. Supply repository credentials privately. |
| Storage | Replace local-path with suitable persistent storage, set StorageClass/reclaim policy, verify scheduling, and test Kamaji etcd backup/restore. |
| Control planes | Size management and tenant control planes, reserve API VIPs/VRRP IDs and test failover. Namespace separation is not by itself a complete security boundary. |
| Network | Allocate management/data subnets, tenant VRFs/VNIs/ASNs, MTUs, NAT/return routes and firewall policies; test management and IPv6 bypass paths. |
| Hardware | Replace all example identities, BMC endpoints and selectors. Validate SKU-specific firmware, hugepages, memory and device-mode settings. |
| DNS/NTP | Supply reachable approved resolvers/time servers for DPU provisioning and runtime. Verify before starting DPU agents. |
| Authentication | Use approved secret delivery for BMC, registry, Git and cluster access. Never commit Secret data, keys, passwords or kubeconfigs. |
| Registries | Mirror/scan required artifacts, pin immutable digests where supported, retain provenance and verify registry TLS/reachability. |
| Hosts | Integrate Ubuntu install/network configuration with the chosen provisioning system, preserving access and rollback. This package does not install host Ubuntu. |
| Reboot lifecycle | Integrate the external reboot method and held node-effect workflow; qualify power-cycle and maintenance handling. |
| Observability | Collect management/tenant/DPU/HBN events and logs with redaction, retention, alerting and health checks. |
| Recovery | Back up state and credentials privately, test restore, and record exact deletion order and recovery access before cleanup. |
| Qualification | Repeat clean deployment, reboot, upgrade/rollback, failure recovery, Internet/data-path and both-direction tenant isolation tests. |

The sample profile uses two distinct IPv4 prefixes. Supporting overlapping tenant
addresses requires distinct routing and conntrack/NAT domains. The lab's IPv4
Internet result does not qualify IPv6 or every protocol for isolation.

The one-file Application uses automatic sync; the separate stage Applications
use manual sync. All use the default project and disable pruning. Restrict project
scope and review hardware consequences before production; do not add DPF-generated
Applications or generated child resources to external Argo desired state.

Do not use the standalone provisioning example for the future NICo-managed stack.
NICo-generated inventory and provisioning resources have a different owner.
