from tests.fixture import WorkbenchTestCase


class RecoveryTests(WorkbenchTestCase):
    def test_original_records_survive_restart(self):
        proof = self.prepare()
        order = self.release_pair(proof)
        receipt = self.start_print(order)['receipt']
        self.void('rA')
        counts = {'start_id': receipt['start_id'], 'good_count': 11, 'waste_count': 3}
        completion = self.post('/finish', **counts)
        self.restart()
        self.assertEqual(proof, self.get('/proof', proof['proof_id']))
        self.assertEqual({'trial_id': 'rA', 'reason': 'sample damaged'}, self.get('/trial', 'rA')['void'])
        self.assertEqual(receipt, self.start_print(order)['receipt'])
        self.assertEqual(completion, self.post('/finish', **counts))
        historical = self.get('/receipt', order['order_id'])
        self.assertEqual(('completed', receipt, completion),
                         (historical['status'], historical['receipt'], historical['completion']))

    def test_pending_request_survives_restart(self):
        proof = self.prepare()
        self.trial(proof, 'front-sample', 'L2')
        self.assertEqual('pending', self.release(proof, 'pending')['status'])
        self.restart()
        self.assertEqual('pending', self.release(proof, 'pending')['status'])
        self.trial(proof, 'back-sample', 'R2')
        result = self.release(proof, 'pending')
        self.assertEqual(('released', 'O-pending', 'A'),
                         (result['status'], result['order']['order_id'], result['order']['register_id']))
