"""Optional DHCP must serve only explicit reservations and preserve lab options."""
import copy
import os
import uuid
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
import test_site_chart


class DHCPChartTests(unittest.TestCase):
    def setUp(self):
        self.site = test_site_chart.SiteChartTests()
        self.values = self.site.values()
        self.values['install-dhcp'] = 'yes'
        for i, reservation in enumerate(self.values['dhcp']['reservations'], 1):
            reservation['mac'] = f'02:00:00:00:00:{i:02x}'

    def test_disabled_dhcp_emits_no_network_resources(self):
        self.values['install-dhcp'] = 'no'
        objects = self.site.objects(self.values)
        self.assertFalse(any(o['metadata'].get('namespace') == 'dpf-network-system' for o in objects))

    def test_config_preserves_all_reservations_and_host_routing_exception(self):
        objects = self.site.objects(self.values)
        cm = next(o for o in objects if o['kind'] == 'ConfigMap')
        config = cm['data']['dnsmasq.conf']
        self.assertIn('dhcp-ignore=tag:!known', config)
        self.assertIn('port=0', config)
        self.assertIn('dhcp-range=192.168.0.128,static,255.255.255.128,30m', config)
        self.assertIn('dhcp-option=option:dns-server\n', config)
        self.assertEqual(config.count('dhcp-host='), 7)
        for mac, ip in [('02:00:00:00:00:01', '192.168.0.244'),
                        ('02:00:00:00:00:02', '192.168.0.242'),
                        ('02:00:00:00:00:03', '192.168.0.246'),
                        ('02:00:00:00:00:04', '192.168.0.249'),
                        ('02:00:00:00:00:05', '192.168.0.241'),
                        ('02:00:00:00:00:06', '192.168.0.243'),
                        ('02:00:00:00:00:07', '192.168.0.232')]:
            line = next(line for line in config.splitlines() if line.startswith('dhcp-host=' + mac))
            self.assertIn(ip, line)
        self.assertIn('dhcp-option=tag:asia-host,option:router\n', config)
        self.assertIn('dhcp-option=tag:asia-host,option:netmask,255.255.255.0', config)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'dnsmasq.conf'
            path.write_text(config)
            result = subprocess.run(['dnsmasq', '--test', '--conf-file=' + str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_one_server_and_config_changes_restart_it(self):
        objects = self.site.objects(self.values)
        deployment = next(o for o in objects if o['kind'] == 'Deployment')
        self.assertEqual(deployment['spec']['replicas'], 1)
        self.assertEqual(deployment['spec']['strategy']['type'], 'Recreate')
        pod = deployment['spec']['template']
        self.assertTrue(pod['spec']['hostNetwork'])
        self.assertEqual(pod['spec']['nodeSelector']['kubernetes.io/hostname'], 'l-ae-1137d-001')
        self.assertFalse(pod['spec']['automountServiceAccountToken'])
        image = pod['spec']['containers'][0]['image']
        self.assertIn('@sha256:', image)
        first = pod['metadata']['annotations']['checksum/config']
        self.values['dhcp']['reservations'][0]['ip'] = '192.168.0.245'
        updated = next(o for o in self.site.objects(self.values) if o['kind'] == 'Deployment')
        self.assertNotEqual(first, updated['spec']['template']['metadata']['annotations']['checksum/config'])

    def test_invalid_or_ambiguous_reservations_are_rejected(self):
        cases = []
        for key, value in [('mac', ''), ('mac', 'not-a-mac'), ('mac', 'ff:ff:ff:ff:ff:ff'),
                           ('mac', '01:00:5e:00:00:01'), ('ip', '192.168.0.200'),
                           ('ip', '192.168.0.129'), ('ip', '192.168.0.254'),
                           ('ip', '10.0.0.2'), ('ip', '192.168.0.128'),
                           ('ip', '192.168.0.255'), ('name', 'bad\ninterface=eth0')]:
            values = copy.deepcopy(self.values)
            values['dhcp']['reservations'][0][key] = value
            cases.append(values)
        for key in ['mac', 'ip', 'name']:
            values = copy.deepcopy(self.values)
            values['dhcp']['reservations'][1][key] = values['dhcp']['reservations'][0][key]
            cases.append(values)
        for key, value in [('install-dhcp', True), ('install-dhcp', 'maybe')]:
            values = copy.deepcopy(self.values)
            values[key] = value
            cases.append(values)
        for values in cases:
            with self.subTest(values=values):
                self.assertNotEqual(self.site.render(values).returncode, 0)

    @unittest.skipUnless(os.environ.get('DSX_DHCP_CONTAINER_TEST') == '1',
                         'opt-in Docker runtime test; uses an isolated internal network')
    def test_runtime_serves_reserved_clients_and_ignores_unknown_clients(self):
        self.values['dhcp']['interface'] = 'eth0'
        objects = self.site.objects(self.values)
        config = next(o for o in objects if o['kind'] == 'ConfigMap')['data']['dnsmasq.conf']
        pod = next(o for o in objects if o['kind'] == 'Deployment')['spec']['template']['spec']
        container = pod['containers'][0]
        prefix = 'dpf-dhcp-check-' + uuid.uuid4().hex[:10]
        network, server = prefix, prefix + '-server'
        def docker(*args):
            return subprocess.run(['docker', *args], capture_output=True, text=True, timeout=60)
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / 'dnsmasq.conf'
            conf.write_text(config)
            script = Path(tmp) / 'lease.sh'
            script.write_text('#!/bin/sh\n[ "$1" = bound ] || exit 0\necho "LEASE ip=$ip subnet=$subnet router=$router dns=$dns"\n')
            script.chmod(0o755)
            result = docker('network', 'create', '--internal', '--subnet', '192.168.0.128/25',
                            '--gateway', '192.168.0.254', network)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                args = ['run', '-d', '--name', server, '--network', network, '--ip', '192.168.0.129',
                        '--read-only', '--tmpfs', '/run/dhcp', '--cap-drop', 'ALL',
                        '--security-opt', 'no-new-privileges', '-v', str(conf) + ':/etc/dpf-dhcp/dnsmasq.conf:ro']
                for cap in container['securityContext']['capabilities']['add']:
                    args.extend(['--cap-add', cap])
                args.extend(['--entrypoint', container['command'][0], container['image'], *container['args']])
                result = docker(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                for suffix, expected in [('01', 'LEASE ip=192.168.0.244 subnet=255.255.255.128 router=192.168.0.254'),
                                         ('07', 'LEASE ip=192.168.0.232 subnet=255.255.255.0 router= dns='),
                                         ('fe', None)]:
                    with self.subTest(client=suffix):
                        result = docker('run', '--rm', '--network', network, '--ip', '192.168.0.130',
                                        '--mac-address', '02:00:00:00:00:' + suffix, '--cap-add', 'NET_ADMIN',
                                        '-v', str(script) + ':/lease.sh:ro', pod['initContainers'][0]['image'],
                                        'udhcpc', '-i', 'eth0', '-n', '-q', '-t', '2', '-T', '2', '-s', '/lease.sh')
                        if expected:
                            self.assertEqual(result.returncode, 0, result.stdout + result.stderr + docker('logs', server).stderr)
                            self.assertIn(expected, result.stdout)
                        else:
                            self.assertNotEqual(result.returncode, 0)
                            self.assertNotIn('LEASE ip=', result.stdout)
            finally:
                docker('rm', '-f', server)
                docker('network', 'rm', network)
