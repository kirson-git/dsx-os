# Optional overlapping tenant subnets

This overlay adds two separate `10.0.0.0/24` IPAM pools with gateway
`10.0.0.254`, each selected into its own tenant cluster. It retains the base
HBN configuration and original pools; it does not switch a live host.

Before selecting these pools, provide independent tenant egress routing and
connection tracking. Changing only the host addresses breaks connectivity.
Management addresses remain unchanged.

For the lab migration, change the existing external Argo Application source
path to `DPF/profiles/two-tenant-hbn/overlapping-subnets`, retaining its site
patches. Change the host-pool reference in Europe’s `DPUService` to
`europe-host-overlap`, and in Asia’s `DPUServiceConfiguration` to
`asia-host-overlap`. Migrate and verify one tenant at a time.

The host targets are Europe `10.0.0.2/24` and Asia `10.0.0.1/24`, each using
its own HBN gateway `10.0.0.254`. Host netplan and external router changes are
not managed by this overlay. Keep the original pools until rollback is no
longer needed. Never reimage a DPU merely to change its HBN subnet.
