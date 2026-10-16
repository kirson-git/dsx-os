import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'charts/site/files'))
import host_reboot


class Fake:
    def __init__(self):
        self.record = None
        self.power = 'On'
        self.serial = 'SERIAL1'
        self.posts = []
        self.ambiguous = False
        self.stuck = False

    def journal(self):
        return copy.deepcopy(self.record)

    def save(self, old, new):
        if old != self.record:
            raise RuntimeError('concurrent update')
        self.record = copy.deepcopy(new)

    def system(self):
        return {'SerialNumber': self.serial, 'PowerState': self.power,
                'Actions': {'#ComputerSystem.Reset': {'target': '/redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset',
                'ResetType@Redfish.AllowableValues': ['GracefulShutdown', 'On']}}}

    def reset(self, action):
        self.posts.append(action)
        if self.ambiguous:
            raise RuntimeError('transport failure after request')
        if not self.stuck:
            self.power = 'Off' if action == 'GracefulShutdown' else 'On'


class RebootTests(unittest.TestCase):
    def run_cycle(self, c, job='job1', method='PowerCycle'):
        host_reboot.recover(c, 'SERIAL1', job, method, attempts=2, sleep=lambda _: None)

    def test_power_cycle_and_retry_are_idempotent(self):
        c = Fake()
        self.run_cycle(c)
        self.assertEqual(c.posts, ['GracefulShutdown', 'On'])
        self.assertEqual(c.record['stage'], 'complete')
        self.run_cycle(c)
        self.assertEqual(len(c.posts), 2)
        self.run_cycle(c, job='new-cycle')
        self.assertEqual(len(c.posts), 4)

    def test_wrong_identity_or_unknown_method_never_reboots(self):
        c = Fake()
        c.serial = 'WRONG'
        with self.assertRaises(RuntimeError): self.run_cycle(c)
        self.assertFalse(c.posts)
        c.serial = 'SERIAL1'
        with self.assertRaises(RuntimeError): self.run_cycle(c, method='Unknown')
        self.assertFalse(c.posts)

    def test_ambiguous_shutdown_is_never_repeated(self):
        c = Fake()
        c.ambiguous = True
        with self.assertRaises(RuntimeError): self.run_cycle(c)
        c.ambiguous = False
        with self.assertRaises(RuntimeError): self.run_cycle(c)
        self.assertEqual(c.posts, ['GracefulShutdown'])

    def test_retry_after_shutdown_can_power_on_without_second_shutdown(self):
        c = Fake()
        c.record = {'job': 'job1', 'serial': 'SERIAL1', 'stage': 'shutdown-requested'}
        c.power = 'Off'
        self.run_cycle(c)
        self.assertEqual(c.posts, ['On'])

    def test_power_on_retry_is_not_repeated_and_requires_on_state(self):
        c = Fake()
        c.record = {'job': 'job1', 'serial': 'SERIAL1', 'stage': 'on-requested'}
        c.power = 'Off'
        with self.assertRaises(RuntimeError): self.run_cycle(c)
        self.assertFalse(c.posts)
        c.power = 'On'
        self.run_cycle(c)
        self.assertEqual(c.record['stage'], 'complete')

    def test_incomplete_prior_cycle_and_changed_identity_are_rejected(self):
        c = Fake()
        c.record = {'job': 'old-job', 'serial': 'SERIAL1', 'stage': 'shutdown-requested'}
        with self.assertRaises(RuntimeError): self.run_cycle(c)
        self.assertFalse(c.posts)
