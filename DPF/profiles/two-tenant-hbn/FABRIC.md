# Fabric and host dependencies

Kubernetes objects alone do not reproduce host Internet access. Supply these
site-specific dependencies before declaring the deployment complete:

1. Reserve tenant API VIPs outside DHCP and provide their management L2 reachability.
2. Provide DPU BMC/OOB access from management-cluster helper pods; host access alone
   may not reach that network. Supply working DNS and NTP before DPU agent startup.
3. Configure the border switch with independent EUROPE and ASIA VRFs, matching
   VNIs/route targets, BGP peers and VTEP underlay reachability.
4. Provide a separate routed egress transit per VRF and advertise only the
   intended default route into each tenant. Avoid route leaking between tenants.
5. Configure egress-router forwarding, tenant return routes and scoped NAT. Allow
   approved DNS, block private/cross-tenant destinations as required, and allow
   established return traffic. Preserve existing unrelated firewall rules.
6. Enforce management-network isolation independently; otherwise a host can
   bypass a data-path isolation demonstration through its management NIC.
7. Configure each Ubuntu PF0 in its tenant subnet, with HBN as default gateway
   and the correct resolver path. Preserve explicit administrator return routes.

The saved baseline used IPv4 egress and blocked IPv6 on tenant transit links.
IPv6 support requires its own routing, DNS, firewall and isolation design.
The two example tenant prefixes do not overlap. Overlapping address spaces need
separate routing and NAT/conntrack domains; do not demonstrate overlap by merely
changing the host addresses in these files.

Switch and router configuration is an external automation stage. This package
contains the requirements, not a universal switch/NAT installer. Capture the
actual running fabric configuration and recovery access before teardown.
