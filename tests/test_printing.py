from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from tests.fixture import WorkbenchTestCase, record_scenario


class PrintingTests(WorkbenchTestCase):
    def test_void_before_start(self):
        proof = self.prepare()
        order = self.release_pair(proof)
        self.trial(proof, 'lB', 'L2', 'B')
        self.trial(proof, 'rB', 'R2', 'B')
        self.void('rA')
        self.assertEqual('B', self.release(proof, 'other-order')['order']['register_id'])
        order_id = order['order_id']
        held = self.get('/receipt', order_id)
        self.assertEqual('recheck_required', held['status'])
        self.assertEqual('A', held['order']['register_id'])
        self.assertIsNone(held['receipt'])
        blocked = self.start_print(order)
        self.assertEqual({'status': 'recheck_required', 'order_id': order_id, 'receipt': None}, blocked)
        self.assertIsNone(self.get('/receipt', order_id)['receipt'])
        self.trial(proof, 'rA-bad', 'R2', right=19)
        self.assertEqual(blocked, self.start_print(order))
        self.trial(proof, 'rA-new', 'R2')
        self.assertEqual('released', self.get('/receipt', order_id)['status'])
        started = self.start_print(order)
        self.assertEqual('started', started['status'])
        self.assertEqual(('A', 'lA', 'rA-new'),
                         tuple(started['receipt'][key] for key in ('register_id', 'front_trial_id', 'back_trial_id')))
        self.assertEqual(started['receipt'], self.get('/receipt', order_id)['receipt'])

    def test_same_register_replacement(self):
        proof = self.prepare()
        order = self.release_pair(proof)
        self.trial(proof, 'rC', 'R2')
        self.trial(proof, 'rB', 'R2')
        self.void('rA')
        self.assertEqual('released', self.get('/receipt', order['order_id'])['status'])
        result = self.start_print(order)
        self.assertEqual('started', result['status'])
        self.assertEqual('rB', result['receipt']['back_trial_id'])

    def test_commit_order(self):
        steps = self.get('/register-tables', 'AB')['steps']
        self.post('/register-tables', table_id='second-context', steps=steps)
        for first in ('void', 'start'):
            with self.subTest(first=first):
                table = 'AB' if first == 'void' else 'second-context'
                proof = self.prepare(edition='ed-' + first, table=table)
                order = self.release_pair(proof, first, prefix=first + '-')
                back_trial = first + '-rA'
                if first == 'void':
                    self.void(back_trial)
                    result = self.start_print(order, confirmation=first)
                    self.assertEqual('recheck_required', result['status'])
                    self.assertIsNone(result['receipt'])
                else:
                    result = self.start_print(order, confirmation=first)
                    self.assertEqual('started', result['status'])
                    self.assertEqual(back_trial, result['receipt']['back_trial_id'])
                    self.void(back_trial)
                handover = self.get('/receipt', order['order_id'])
                self.assertEqual(result['status'], handover['status'])
                self.assertEqual(result['receipt'], handover['receipt'])

    def test_concurrent_start_and_void_agree_with_committed_receipt(self):
        proof = self.prepare()
        order = self.release_pair(proof)
        gate = Barrier(2, timeout=5)

        def start():
            gate.wait()
            return self.start_print(order)

        def void():
            gate.wait()
            return self.void('rA')

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempted_start = pool.submit(start)
            attempted_void = pool.submit(void)
            result = attempted_start.result(timeout=12)
            self.assertEqual('rA', attempted_void.result(timeout=12)['trial_id'])
        final = self.get('/receipt', order['order_id'])
        self.assertEqual(result['status'], final['status'])
        self.assertEqual(result['receipt'], final['receipt'])
        if result['status'] == 'started':
            self.assertEqual(('A', 'lA', 'rA'), tuple(result['receipt'][key]
                             for key in ('register_id', 'front_trial_id', 'back_trial_id')))
        else:
            self.assertEqual('recheck_required', result['status'])
            self.assertIsNone(result['receipt'])

    def test_completed_handover(self):
        proof = self.prepare()
        order = self.release_pair(proof)
        start = self.start_print(order)['receipt']
        order_id = order['order_id']
        first = self.get('/receipt', order_id)
        self.assertEqual(start, first['receipt'])
        self.assertEqual('rA', start['back_trial_id'])
        self.void('rA')
        self.trial(proof, 'rReplacement', 'R2')
        completion = self.post('/finish', start_id=start['start_id'], good_count=42, waste_count=2)
        final = self.get('/receipt', order_id)
        self.assertEqual('completed', final['status'])
        self.assertEqual(first['receipt'], final['receipt'])
        self.assertEqual({'start_id': start['start_id'], 'good_count': 42, 'waste_count': 2}, completion)
        self.assertEqual(completion, final['completion'])
        record_scenario('n8', {'start_trials': ['lA', 'rA'], 'later_void': 'rA',
                               'later_trial': 'rReplacement', 'finish_counts': [42, 2]},
                        ['A', 'lA', 'rA'], [final['receipt'][key] for key in
                                           ('register_id', 'front_trial_id', 'back_trial_id')],
                        [42, 2], [final['completion']['good_count'], final['completion']['waste_count']],
                        ['printing/receipts.py', 'printing/completion.py', 'printing/handover.py'],
                        'Use the original mounted samples for historical provenance and the separate accepted finish counts for completion.')

    def test_finish_counts(self):
        order = self.release_pair(self.prepare())
        self.post('/finish', code=400, start_id='S-' + order['order_id'], good_count=0, waste_count=0)
        receipt = self.start_print(order)['receipt']
        for good, waste in ((-1, 0), (0, -1), (True, 0), (0, 1.0)):
            with self.subTest(good=good, waste=waste):
                self.post('/finish', code=400, start_id=receipt['start_id'], good_count=good, waste_count=waste)
                self.assertIsNone(self.get('/receipt', order['order_id'])['completion'])
        self.post('/finish', code=400, start_id=receipt['start_id'], good_count=0)
        done = self.post('/finish', start_id=receipt['start_id'], good_count=0, waste_count=0)
        self.assertEqual(done, self.get('/receipt', order['order_id'])['completion'])
        self.assertEqual((0, 0), (done['good_count'], done['waste_count']))

    def test_confirmation_replay(self):
        proof = self.prepare()
        order = self.release_pair(proof)
        first = self.start_print(order)
        self.void('rA')
        self.assertEqual(first, self.start_print(order))
        self.start_print(order, confirmation='second', code=400)
        self.trial(proof, 'replacement', 'R2')
        second_order = self.release(proof, 'second-order')['order']
        self.start_print(second_order, code=400)
        self.assertIsNone(self.get('/receipt', second_order['order_id'])['receipt'])
        data = {'start_id': first['receipt']['start_id'], 'good_count': 7, 'waste_count': 1}
        finish = self.post('/finish', **data)
        self.assertEqual(finish, self.post('/finish', **data))
        self.post('/finish', code=400, **dict(data, waste_count=2))
        final = self.get('/receipt', order['order_id'])
        self.assertEqual(finish, final['completion'])
        self.assertEqual(first['receipt'], final['receipt'])
