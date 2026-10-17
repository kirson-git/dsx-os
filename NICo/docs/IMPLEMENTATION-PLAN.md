# NICo + DPF GitOps implementation plan

Goal: prepare a reproducible Argo CD package for NICo Core 2.2.2 with DPF
26.4.0, without deploying to the active standalone DPF lab.

Architecture: external Argo renders a stack chart from one editable Application.
Each child Application owns one release. Stages retain earlier Applications.
The pinned upstream Core chart stays upstream; the small prerequisites chart is
vendored with explicit Argo hook adaptation to preserve generated credentials.
Vault initialization and credential seeding are private operator operations.

- [x] Pin and inspect the NICo source, DPF requirements and chart contracts.
- [x] Add staged stack chart, one settings file, values and Vault TLS bootstrap.
- [x] Add private credential and Vault initialization guidance/tools.
- [x] Render upstream/Core/prerequisite charts; test ownership and stage boundaries.
- [x] Document differences, DHCP, production changes and qualification limits.
- [x] Run validation in tmux and review outputs.

Publication is recorded in the repository commit history.

Scope: Core API, BMC proxy, DHCP, DNS, NTP, PXE and SSH console; DPF operator,
Kamaji and DPU services. REST multi-site API, Flow and RMS are separate extensions
and their prerequisites are documented, not silently enabled by this profile.
No full clean hardware rebuild or production readiness claim without live tests.
