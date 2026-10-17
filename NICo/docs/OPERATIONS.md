# Operations and production changes

## Inspect progress

```bash
kubectl -n argocd get applications -l dsx.nvidia.com/stack=nico
kubectl -n nico-system get pods,pvc
kubectl -n vault get pods,pvc
kubectl -n postgres get pods,pvc
kubectl -n dpf-operator-system get pods,dpuclusters,dpus
kubectl -n nico-system logs job/vault-pki-config -c configure --tail=60
kubectl -n nico-system logs deployment/nico-api --tail=100
```

Missing resources during an earlier stage are expected. An Argo Application being
Synced does not prove that DHCP, Redfish, PXE or DPU data traffic works.

## Hardware onboarding

1. Confirm NICo Core is healthy, DPF is reconciled and credentials are seeded.
2. Test BMC/Redfish reachability from the management cluster network.
3. Reserve/relay the provisioning subnet and configure its network in NICo.
4. Add approved expected-machine inventory with correct BMC/MAC and matching
   factory credentials using the NICo 2.2.2 admin CLI.
5. Enable DPF integration and restart Core as described in the README.
6. Monitor discovery, DPU provisioning, OS boot and service readiness before
   creating instances. Confirm host traffic and tenant isolation separately.

The package does not invent expected machines or reboot existing hosts.
Use the pinned upstream onboarding documentation and the matching CLI `--help`;
no unverified hardware ingestion command is supplied here.

## Production checklist

- Use a clean target or an explicit ownership migration. Do not overlap the
  standalone DPF Applications with these NICo Applications.
- Pin `revision` and `spec.source.targetRevision` to your reviewed Git commit.
  The public starter follows `main`; Core itself is pinned by commit.
- Use supported Kubernetes/CNI/CSI and verify DPF hardware/firmware compatibility.
- Provide three failure domains and capacity. Vault alone requests 2 CPU and
  8 GiB per replica in the inherited values. Check the remaining pod requests.
- Prefer durable CSI with tested snapshots, restore and topology scheduling.
  Lab local-path uses host disks and Delete reclaim policy; it is not HA storage.
- Replace self-signed development PKI with your trust model; secure Vault unseal,
  root-token lifecycle, backups and Kubernetes Secret encryption.
- Validate and scan every image, pin immutable artifacts for your deployment,
  and confirm both boot-artifact architectures exist before Core installation.
- Supply working Unbound and exporter images matching the upstream chart's
  entrypoint/config contract. `CHANGE_ME` intentionally blocks live submission.
- Configure DNS, DHCP relay, routed VIPs, firewall rules, BMC reachability and
  fabric routing. Never let two DHCP servers answer the same provisioning scope.
- Restrict Argo RBAC/projects and UI exposure. The starter uses project `default`.
- Test BMC credential validation, BFB delivery, DPU join, host boot and network
  isolation before calling the deployment production-ready.

## Overrides and lifecycle

`coreExtraValues` merges into the pinned upstream Core Helm values. It can
replace generated settings; TOML strings replace as a whole, not line by line.
Review the rendered result when using it. It must never contain credentials.
Other component-specific values live in `NICo/values/` in your Git fork.

Stages are additive and do not uninstall earlier stages. Pruning and cascade
finalizers are disabled so a settings mistake cannot silently delete databases,
Vault or DPUs. Removing the parent Application does not delete the stack.
There is deliberately no destructive cleanup command in this first NICo profile.
Plan data/credential preservation and hardware ownership before teardown.

The bootstrap `seed` action stores credentials only; it does not test them against
BMCs. It is not the standalone DPF credential preflight tool.
