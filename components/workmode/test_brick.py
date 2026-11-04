import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import brick_bridge as bridge
import brick_mac as mac


class BridgeTests(unittest.TestCase):
    def test_disconnect_restart_and_staleness_never_release_latch(self):
        with tempfile.TemporaryDirectory() as d:
            now = [0.0]
            path = Path(d) / 'state.json'
            state = bridge.State(path, lambda: now[0])
            def observe(value):
                state.observe({'event':'state','capability':'brick','state':value,
                    'source':'accessibility_service_configuration','versionTested':True})
            observe('bricked')
            self.assertEqual(state.snapshot()['state'], 'bricked')
            now[0] = 11
            self.assertEqual(state.snapshot()['state'], 'unknown')
            self.assertTrue(state.snapshot()['latchedBricked'])
            state.disconnect()
            restored = bridge.State(path)
            self.assertEqual(restored.snapshot()['state'], 'unknown')
            self.assertTrue(restored.snapshot()['latchedBricked'])
            observe('unknown')
            self.assertTrue(state.snapshot()['latchedBricked'])
            observe('unbricked')
            self.assertFalse(state.snapshot()['latchedBricked'])
            self.assertFalse(bridge.State(path).snapshot()['latchedBricked'])

    def test_future_brick_version_keeps_using_recognized_signal(self):
        with tempfile.TemporaryDirectory() as d:
            state = bridge.State(Path(d) / 'state.json')
            state.observe({'event': 'state', 'capability': 'brick', 'state': 'bricked',
                'source': 'accessibility_service_configuration', 'versionTested': False})
            self.assertEqual(state.snapshot()['state'], 'bricked')
            self.assertTrue(state.snapshot()['latchedBricked'])
            self.assertFalse(state.snapshot()['versionTested'])
            state.observe({'event': 'state', 'capability': 'brick', 'state': 'unbricked',
                'source': 'unrecognized'})
            self.assertEqual(state.snapshot()['state'], 'unknown')
            self.assertTrue(state.snapshot()['latchedBricked'])

    def test_non_tailnet_destinations(self):
        self.assertTrue(bridge.tailnet('100.84.182.122'))
        self.assertFalse(bridge.tailnet('127.0.0.1'))
        self.assertFalse(bridge.tailnet('192.168.1.1'))
        self.assertFalse(bridge.tailnet('8.8.8.8'))


class ControllerTests(unittest.TestCase):
    def backend(self, sessions=()):
        b = Mock()
        b.sessions.return_value = list(sessions)
        b.prepare_brick.return_value = 7
        return b

    def test_paused_saved_intention_is_replaced_and_then_reused(self):
        from test_workmode import intention, P
        saved = intention()
        saved['name'] = mac.name_for(P)
        saved['conditions'][1]['rule'] = {'type': 'manual'}
        paused = dict(saved, pausedAt=123, id=1)
        backend = mac.Backend()
        backend.intentions = Mock(return_value=[paused])
        with patch.object(mac, 'control', return_value=saved) as create:
            self.assertEqual(backend.prepare_brick(P), saved['id'])
            create.assert_called_once()
        backend.intentions.return_value = [paused, saved]
        with patch.object(mac, 'control') as create:
            self.assertEqual(backend.prepare_brick(P), saved['id'])
            create.assert_not_called()

    def test_unknown_preserves_and_recovers_lock(self):
        b = self.backend()
        self.assertTrue(mac.reconcile({}, b, {'state':'unknown','latchedBricked':False}, True))
        b.start.assert_called_once_with(7)
        b.release_brick.assert_not_called()

    def test_explicit_unbrick_releases_only_brick_owned_sessions(self):
        b = self.backend([{'id':7,'name':mac.PREFIX+'abc'}, {'id':9,'name':'Workmode/study/manual'}])
        self.assertFalse(mac.reconcile({}, b, {'state':'unbricked','latchedBricked':False}, True))
        b.release_brick.assert_called_once_with(7)
        b.start.assert_not_called()

    def test_never_unlocks_on_missing_or_stale_observations(self):
        for data in ({}, {'schema':1,'state':'unbricked','latchedBricked':False,'ageSeconds':11},
                     {'schema':1,'state':'unbricked','latchedBricked':True,'ageSeconds':1},
                     {'schema':1,'state':'unbricked','latchedBricked':False,'ageSeconds':float('nan')}):
            with self.assertRaises(mac.w.Error): mac.validate(data)

    def test_repeated_bricked_observations_are_idempotent(self):
        b = self.backend([{'id':7,'name':mac.PREFIX+'abc'}])
        self.assertTrue(mac.reconcile({}, b, {'state':'bricked','latchedBricked':True}, True))
        b.prepare_brick.assert_not_called()
        b.start.assert_not_called()

    def test_initial_unknown_does_not_invent_a_lock(self):
        b = self.backend()
        self.assertFalse(mac.reconcile({}, b, {'state':'unknown','latchedBricked':False}, False))
        b.start.assert_not_called()

    def test_failed_release_does_not_return_unlatched(self):
        b = self.backend([{'id':7,'name':mac.PREFIX+'abc'}])
        b.release_brick.side_effect = mac.w.Error('Phone bricked again')
        with self.assertRaises(mac.w.Error):
            mac.reconcile({}, b, {'state':'unbricked','latchedBricked':False}, True)


if __name__ == '__main__': unittest.main()
