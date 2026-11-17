# Validation boundary

The inherited chart-renderer baseline passed 22 tests before import. This package
adds external/service Argo separation, CRD placement and Redis hook conversion tests.
The private working lab's 30 root CR definitions passed server-side dry-run before
sanitization. Public examples replace live addresses/identities and require their
own validation after site edits.

No destructive cleanup, fresh external-Argo installation or full hardware rebuild
has been performed as part of this repository preparation. The public profile is
not a claim that example hardware was provisioned. A separate cluster and an
existing external Argo require integration qualification.

Run local checks from the repository root:

```bash
python3 -m unittest discover -s DPF/tests -v
```

Tests require Helm, PyYAML and jsonschema. Rendering both same-cluster and
separate-cluster modes is offline; no authentication or cluster writes occur.

Preparation checks completed: 29 tests passed, 30 public profile custom resources
passed bundled CRD-schema validation, Application schemas validated, Markdown lint
and local links passed, and the simple Helm recipe rendered with shared CRDs
omitted. Chart checksums and the staged payload scan passed. A review found and
removed controller-owned dependency labels from the profile; the default Helm
scheduling requirement is documented. These checks do not replace live rebuild
qualification.

The one-file entry point and five stage Applications passed Application CRD schema
validation. The 12 new readiness/RBAC resources passed server-side dry-run. Bash
credential tests cover hidden payload handling, cleanup, invalid input and rejecting
repository-contained temporary directories, including symlinks. These checks do
not execute a real install or validate real BMC authentication.

A bootstrap regression check prevents waiting for overall DPF readiness before
DPU provisioning. The gate uses the pinned controller's `SystemComponentsReconciled`
condition instead. Full readiness remains a post-provisioning validation.
