# DPF site chart (maintainers)

Customer entry point: [DPF/config.yaml](../../config.yaml). Customers edit that
Application's `spec.source.helm.valuesObject`; Argo renders this chart from Git.
It requires the separately installed DPF platform. It does not install BFBs,
DPU inventory or HBN. See the [short guide](../../README.md).

Required values: `apiServerIP`, `vipInterface`, `europeVIP`, `asiaVIP`.
`apiServerPort` defaults to integer `6443` (1–65535); add it beside `apiServerIP`
when needed. Endpoints are distinct unicast IPv4 addresses; the interface is
1–15 letters/digits/underscores/dots/hyphens, starting without a dot. IPv6 and
DNS endpoint names are not supported by this chart. Unknown keys fail validation.

`install-dhcp` defaults to the string `"no"`; `"yes"` enables the optional
[DHCP component](../../DHCP.md). Blank MACs are accepted only while DHCP is off.
Pruning and self-healing are disabled. Applying the Application starts sync;
later Git changes can also trigger sync. No deletion finalizer is added.

`files/resources.json` is generated from the canonical operator/tenant stages
under `profiles/two-tenant-hbn/desired/`. Never edit it manually. The template
changes only the API endpoint, tenant VIPs and Keepalived interface. Preserve
Argo readiness hooks and resource identities when updating the source profiles.

```bash
# Run from the repository root after changing canonical profiles:
python3 DPF/tools/package_site.py
python3 DPF/tools/package_site.py --check
python3 -m unittest discover -s DPF/tests

# Optional real DHCP exchanges on an isolated internal Docker network:
DSX_DHCP_CONTAINER_TEST=1 python3 -m unittest discover \
  -s DPF/tests -p test_dhcp_chart.py
```

The runtime test uses synthetic MACs and does not attach to the lab network.
It needs a running Docker daemon and permission to create temporary containers
and an internal network. It cleans up the resources it creates.
