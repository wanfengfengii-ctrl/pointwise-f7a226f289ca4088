from concurrent.futures import ThreadPoolExecutor
from functools import partial
from threading import Barrier

from printing.press_device import open_press
from printing.press_exercise import run_press_wheel
from tests.fixture import WorkbenchTestCase


class PressWheelTests(WorkbenchTestCase):
    def setUp(self):
        super().setUp()
        # The workbench locates the press file from the workbench database path.
        self.open_device = partial(open_press, self.database)

    def _raw_post(self, path, **data):
        return self._send(path, data)

    def _raw_get(self, path, identity):
        from urllib.parse import urlencode
        return self._send(path + '?' + urlencode({'id': identity}))

    def _wheel(self, mode):
        return run_press_wheel(self._raw_post, self._raw_get, self.open_device, mode=mode)

    def test_wheel_drain_branch(self):
        result = self._wheel('drain')
        a1 = result['turns']['turn-A1']
        self.assertEqual(103, a1['end_counter'])
        self.assertEqual(3, a1['count'])
        self.assertEqual(107, result['final_counter'])
        self.restart()
        # Reopening uses the same database and press file: original ids read the same results.
        turn = self.get('/press-turn', 'turn-A1')
        self.assertEqual(100, turn['start_counter'])
        self.assertEqual(103, turn['end_counter'])
        self.assertEqual(3, turn['count'])
        handover = self.get('/receipt', result['orders']['A'])
        self.assertEqual('completed', handover['status'])
        self.assertEqual(result['handovers']['A']['press_turns'], handover['press_turns'])
        handover_b = self.get('/receipt', result['orders']['B'])
        self.assertEqual(1, len(handover_b['press_turns']))

    def test_wheel_cutover_branch(self):
        result = self._wheel('cutover')
        a1 = result['turns']['turn-A1']
        self.assertEqual(102, a1['end_counter'])
        self.assertEqual(2, a1['count'])
        self.assertEqual(107, result['final_counter'])
        self.restart()
        turn = self.get('/press-turn', 'turn-A1')
        self.assertEqual(100, turn['start_counter'])
        self.assertEqual(102, turn['end_counter'])
        self.assertEqual(2, turn['count'])
        # Replaying an already yielded turn only reads back the stored segment.
        yielded = self.post('/press-yield', turn_id='turn-A1')
        self.assertEqual(turn, yielded)
        handover = self.get('/receipt', result['orders']['A'])
        self.assertEqual([100, 102], [handover['press_turns'][0]['start_counter'],
                                     handover['press_turns'][0]['end_counter']])

    def test_segmented_start_and_replay_rules(self):
        orders = self._prepare_two_orders()
        start = self.post('/start', order_id=orders['A'], confirmation_id='mount-A',
                          target_count=5)
        self.assertEqual(5, start['receipt']['target_count'])
        # Same confirmation must keep mode and target.
        replay = self.post('/start', order_id=orders['A'], confirmation_id='mount-A',
                           target_count=5)
        self.assertEqual(start['receipt'], replay['receipt'])
        self.post('/start', code=400, order_id=orders['A'], confirmation_id='mount-A')
        self.post('/start', code=400, order_id=orders['A'], confirmation_id='mount-A',
                  target_count=6)
        self.post('/start', code=400, order_id=orders['A'], confirmation_id='other-mount',
                  target_count=5)
        for bad in (0, -1, 1.5, True, '5'):
            with self.subTest(bad=bad):
                self.post('/start', code=400, order_id=orders['B'],
                          confirmation_id='mount-B', target_count=bad)
        unknown = self.post('/start', code=404, order_id='O-missing',
                            confirmation_id='mount-x', target_count=3)
        self.assertEqual('not_found', unknown['status'])

    def test_turn_lifecycle_and_quota(self):
        orders = self._prepare_two_orders()
        start_a = self.post('/start', order_id=orders['A'], confirmation_id='mount-A',
                            target_count=5)['receipt']
        start_b = self.post('/start', order_id=orders['B'], confirmation_id='mount-B',
                            target_count=2)['receipt']
        self.get('/press-turn', 'missing', code=404)
        turn = self.post('/press-turn', start_id=start_a['start_id'], turn_id='turn-A1')
        self.assertEqual({'status': 'active', 'turn_id': 'turn-A1',
                          'start_id': start_a['start_id'], 'start_counter': 100,
                          'end_counter': None, 'count': None}, turn)
        # Replaying the same open is a read; another start id on the same turn conflicts.
        self.assertEqual(turn, self.post('/press-turn', start_id=start_a['start_id'],
                                         turn_id='turn-A1'))
        self.post('/press-turn', code=400, start_id=start_b['start_id'],
                  turn_id='turn-A1')
        # B cannot occupy the press while A holds it.
        self.post('/press-turn', code=400, start_id=start_b['start_id'],
                  turn_id='turn-B1')
        # Normal (non-segmented) orders cannot use the segmented endpoints.
        normal_order = self.release_pair(self.prepare(edition='plain-edition'))
        normal = self.start_print(normal_order)['receipt']
        self.post('/press-turn', code=400, start_id=normal['start_id'], turn_id='turn-n')
        self.post('/press-feed', code=404, turn_id='turn-n', count=1)
        # Feed beyond the order remainder is rejected before touching the device.
        self.post('/press-feed', code=400, turn_id='turn-A1', count=6)
        self.post('/press-feed', code=400, turn_id='turn-A1', count=0)
        with self.open_device() as press:
            self.assertEqual(100, press.read().counter)
        with self.open_device() as press:
            press.interrupt_next_feed(after=2)
        feed = self.post('/press-feed', code=202, turn_id='turn-A1', count=3)
        self.assertEqual({'status': 'pending', 'turn_id': 'turn-A1', 'count': 3}, feed)
        # Same parameters replay the same feed; the reply stays pending until drained.
        self.assertEqual(feed, self.post('/press-feed', code=202, turn_id='turn-A1', count=3))
        self.post('/press-feed', code=400, turn_id='turn-A1', count=4)
        with self.open_device() as press:
            self.assertEqual(102, press.read().counter)

        yielding = self.post('/press-yield', code=202, turn_id='turn-A1')
        self.assertEqual('yielding', yielding['status'])
        self.assertIsNone(yielding['end_counter'])
        # Same-parameter replay still returns the original pending feed without a second feed.
        self.assertEqual(feed, self.post('/press-feed', code=202, turn_id='turn-A1', count=3))
        # A different feed cannot start once handover has begun.
        self.post('/press-feed', code=400, turn_id='turn-A1', count=1)
        with self.open_device() as press:
            press.lose_next_advance()
        self.post('/press-yield', code=202, turn_id='turn-A1')
        yielded = self.post('/press-yield', turn_id='turn-A1')
        self.assertEqual(102, yielded['end_counter'])
        self.assertEqual(2, yielded['count'])
        # No second first feed after the segment is sealed.
        self.post('/press-feed', code=400, turn_id='turn-A1', count=1)
        # A query never advances state.
        self.assertEqual(yielded, self.get('/press-turn', 'turn-A1'))

    def test_empty_turn_yields_zero(self):
        orders = self._prepare_two_orders()
        start_a = self.post('/start', order_id=orders['A'], confirmation_id='mount-A',
                            target_count=5)['receipt']
        self.post('/press-turn', start_id=start_a['start_id'], turn_id='turn-empty')
        yielded = self.post('/press-yield', turn_id='turn-empty')
        self.assertEqual(100, yielded['start_counter'])
        self.assertEqual(100, yielded['end_counter'])
        self.assertEqual(0, yielded['count'])
        # Remainder is still the full target.
        self.post('/press-turn', start_id=start_a['start_id'], turn_id='turn-next')
        self.post('/press-feed', turn_id='turn-next', count=5)
        full = self.post('/press-yield', turn_id='turn-next')
        self.assertEqual(5, full['count'])
        self.post('/finish', start_id=start_a['start_id'], good_count=5, waste_count=0)

    def test_finish_guards_for_segmented_orders(self):
        orders = self._prepare_two_orders()
        start_a = self.post('/start', order_id=orders['A'], confirmation_id='mount-A',
                            target_count=5)['receipt']
        self.post('/press-turn', start_id=start_a['start_id'], turn_id='turn-A1')
        self.post('/press-feed', turn_id='turn-A1', count=3)
        # Still occupying the press.
        self.post('/finish', code=400, start_id=start_a['start_id'],
                  good_count=3, waste_count=0)
        self.post('/press-yield', turn_id='turn-A1')
        # Target not reached.
        self.post('/finish', code=400, start_id=start_a['start_id'],
                  good_count=3, waste_count=0)
        self.post('/press-turn', start_id=start_a['start_id'], turn_id='turn-A2')
        self.post('/press-feed', turn_id='turn-A2', count=2)
        self.post('/press-yield', turn_id='turn-A2')
        # Target reached but good + waste does not equal the confirmed count.
        self.post('/finish', code=400, start_id=start_a['start_id'],
                  good_count=4, waste_count=0)
        sealed = self.post('/finish', start_id=start_a['start_id'],
                           good_count=4, waste_count=1)
        # Conflicting reseal is rejected; identical reseal reads back.
        self.post('/finish', code=400, start_id=start_a['start_id'],
                  good_count=3, waste_count=2)
        self.assertEqual(sealed, self.post('/finish', start_id=start_a['start_id'],
                                           good_count=4, waste_count=1))
        handover = self.get('/receipt', orders['A'])
        self.assertEqual('completed', handover['status'])
        self.assertEqual(sealed, handover['completion'])

    def test_normal_orders_keep_original_shape(self):
        order = self.release_pair(self.prepare(edition='normal-edition'))
        started = self.start_print(order)
        self.assertNotIn('target_count', started['receipt'])
        done = self.post('/finish', start_id=started['receipt']['start_id'],
                         good_count=7, waste_count=1)
        self.assertEqual(7, done['good_count'])
        handover = self.get('/receipt', order['order_id'])
        self.assertNotIn('press_turns', handover)
        self.assertEqual('completed', handover['status'])

    def test_concurrent_open_only_one_order_wins_the_press(self):
        orders = self._prepare_two_orders()
        start_a = self.post('/start', order_id=orders['A'], confirmation_id='mount-A',
                            target_count=5)['receipt']
        start_b = self.post('/start', order_id=orders['B'], confirmation_id='mount-B',
                            target_count=2)['receipt']
        gate = Barrier(2, timeout=10)

        def call(start_id, turn_id):
            gate.wait()
            return self._send('/press-turn', {'start_id': start_id, 'turn_id': turn_id})

        with ThreadPoolExecutor(max_workers=2) as pool:
            result_a = pool.submit(call, start_a['start_id'], 'turn-A1')
            result_b = pool.submit(call, start_b['start_id'], 'turn-B1')
            response_a, response_b = result_a.result(timeout=20), result_b.result(timeout=20)
        self.assertEqual([200, 400], sorted((response_a[0], response_b[0])))
        winner = response_a if response_a[0] == 200 else response_b
        winner_id = winner[1]['turn_id']
        self.post('/press-yield', turn_id=winner_id)
        loser_start = start_b['start_id'] if winner_id == 'turn-A1' else start_a['start_id']
        loser_id = 'turn-B1' if winner_id == 'turn-A1' else 'turn-A1'
        self.assertEqual('active', self.post('/press-turn', start_id=loser_start,
                                             turn_id=loser_id)['status'])

    def _prepare_two_orders(self):
        from printing.press_exercise import prepare_orders
        return prepare_orders(lambda path, **data: self.post(path, **data))