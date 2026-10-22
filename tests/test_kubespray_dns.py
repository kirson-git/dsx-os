"""Exercise the resolver program emitted by the standalone Kubespray wizard."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


SCRIPT = Path(__file__).resolve().parents[1] / "kubespray-wizard.sh"


class ResolverTests(unittest.TestCase):
    def test_deployment_uses_override_only_after_successful_dns_preparation(self):
        for fail_dns in (False, True):
            with self.subTest(fail_dns=fail_dns), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "functions.sh"
                source.write_text(SCRIPT.read_text().rsplit('main "$@"', 1)[0])
                (root / "infra/kubespray/inventories/example").mkdir(parents=True)
                result = subprocess.run(
                    ["bash", "-c", '''
source "$1"
AUTO_APPROVE=true
prepare_kubespray_image() { :; }
run_kubespray_container() {
  printf '%s\\n' "$*" >> calls.txt
  if [[ $* == *prepare-dns.yml* && $2 == ansible-playbook && $FAIL_DNS == true ]]; then
    return 42
  fi
}
run_preflight_and_apply example
''', "test", str(source)], cwd=root, capture_output=True, text=True,
                    env={**os.environ, "FAIL_DNS": str(fail_dns).lower()},
                )
                calls = (root / "calls.txt").read_text().splitlines()
                if fail_dns:
                    self.assertEqual(result.returncode, 42, result.stderr)
                    self.assertFalse(any(" cluster.yml" in c for c in calls))
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("prepare-dns.yml", calls[-2])
                    self.assertIn("--extra-vars @/inventory/dns-extra-vars.yml", calls[-1])
                    override = yaml.safe_load((root / "infra/kubespray/inventories/example/dns-extra-vars.yml").read_text())
                    self.assertEqual(override["kube_resolv_conf"], "/etc/kubernetes/kubelet-resolv.conf")

    def render(self, resolver, upstream=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "functions.sh"
            source.write_text(SCRIPT.read_text().rsplit('main "$@"', 1)[0])
            playbook = root / "dns.yml"
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; write_dns_playbook "$2"',
                 "test", str(source), str(playbook)], capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            tasks = yaml.safe_load(playbook.read_text())[0]["tasks"]
            code = next(t["ansible.builtin.command"]["argv"][2]
                        for t in tasks if "ansible.builtin.command" in t)
            resolv = root / "resolv.conf"
            resolv.write_text(resolver)
            return subprocess.run(
                ["python3", "-c", code, json.dumps(upstream or []),
                 "10.233.0.0/18,10.233.64.0/18", "cluster.local", str(resolv)],
                capture_output=True, text=True,
            )

    def test_excludes_cluster_and_stub_and_caps_deduplicated_upstreams(self):
        result = self.render(
            "nameserver 10.233.0.3\nnameserver 127.0.0.53\n"
            "nameserver 192.0.2.53\nnameserver 192.0.2.53\n"
            "nameserver 192.0.2.54\nnameserver 192.0.2.55\n"
            "nameserver 192.0.2.56\n"
            "search default.svc.cluster.local svc.cluster.local example.test\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "nameserver 192.0.2.53\nnameserver 192.0.2.54\n"
                         "nameserver 192.0.2.55\nsearch example.test\n")

    def test_explicit_inventory_upstreams_take_precedence(self):
        result = self.render("nameserver 192.0.2.53\n", ["198.51.100.53"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "nameserver 198.51.100.53\n")

    def test_no_usable_resolver_fails_before_writing_configuration(self):
        result = self.render("nameserver 127.0.0.53\nnameserver 10.233.0.3\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No usable upstream DNS", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
