# NICo GitOps rules

- Keep this package separate from standalone DPF; never claim both may own the
  same DPF resources. Do not deploy into the active lab without authorization.
- `config.yaml` is the single site-settings entry point. Secrets and real MACs
  stay outside Git. Avoid adding another site configuration file.
- External Argo owns prerequisites/Core; service Argo owns DPU workloads.
- Pin upstream contracts and inspect code before changing image/chart values.
- Keep the short README sequential. Put details in `docs/` and link them.
- Do not claim production readiness from Helm renders. Record live qualification
  separately, including DHCP, Redfish, BFB delivery and host data-plane tests.
- Before publishing: run tests and full chart validation from `docs/VALIDATION.md`.
- The build server is only for builds/artifact verification, never lab deployment.
