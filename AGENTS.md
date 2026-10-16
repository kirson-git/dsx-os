# Customer installer rules

- Keep changes small and preserve the working workflow. Do not turn a settings
  or README edit into a new chart, framework, or installer redesign.
- Name the exact file to edit and give complete copy-paste commands. Prefer one
  customer-facing site YAML; mark editable values `# please change here`.
- Prefill verified lab values when requested. Explain DHCP versus manual IPs,
  where DHCP runs, and whether this package installs it. Never guess addresses.
- Describe actual scope: `DPF/config.yaml` configures the operator and tenants
  after platform installation; optional DHCP uses the same file. HBN and
  provisioning remain separate stages.
- Keep the README short: numbered steps and a simple diagram; link longer guides.
- Validate YAML rendering, commands, links and Markdown. When publication is
  authorized, commit/push and verify the remote revision before sharing Git links.
- When the user will run/test the commands, leave deployment to them.
- Keep real lab MAC addresses local; public templates have blank MAC fields.
- Keep passwords, tokens, private keys and kubeconfigs out of Git. Use
  `DPF/credentials.sh` for the BMC Secret. Respect instructions not to make backups.
- **Architecture:** external Argo is shared; DPF and NICo have separate entry files.
  Standalone DPF must work without NICo. Define ownership before NICo integration;
  never manage one resource through overlapping Applications. Keep DPF service
  Argo separate from external Argo. NICo integration is planned, not implemented.
- Teardown: drain services before tenant APIs; reclaim volumes before storage;
  verify retained CRDs separately. Preserve management Kubernetes and external
  Argo unless their deletion is explicitly requested.
- Keep customer deployment files here and NICo source/build work in its own repo.
  `nico-build-01` (`10.220.175.23`) is build-only, never for lab administration.

Package details: [DPF/Argo skill](.agents/skills/dsx-dpf-argo/SKILL.md).
The user's latest instructions take precedence over these defaults.
