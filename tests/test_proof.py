from tests.fixture import WorkbenchTestCase, record_scenario


class ProofTests(WorkbenchTestCase):
    def test_shared_register(self):
        proof = self.prepare()
        for trial_id, face, left, right in (('lA', 'L2', 15, 30), ('rA', 'R2', 25, 25)):
            trial = self.trial(proof, trial_id, face, left=left, right=right)
            self.assertEqual({'face_id': face, 'paper_id': 'P600', 'table_id': 'AB', 'register_id': 'A'},
                             trial['condition'])
            self.assertTrue(trial['result']['passed'])
        result = self.release(proof)
        self.assertEqual('released', result['status'])
        order = result['order']
        self.assertEqual('A', order['register_id'])
        self.assertEqual(proof['proof_id'], order['proof_id'])
        self.assertEqual('released', self.get('/receipt', order['order_id'])['status'])

    def test_measured_shortfall(self):
        proof = self.prepare()
        self.assertTrue(proof['settings']['A']['back']['can_trial'])
        self.trial(proof, 'lA', 'L2')
        right = self.trial(proof, 'rA', 'R2', left=25, right=19)
        self.assertEqual({'measured': {'left_mm': 25, 'right_mm': 19}, 'passed': False,
                          'reasons': ['right_below_limit']}, right['result'])
        self.assertEqual(right, self.get('/trial', 'rA')['trial'])
        self.assertEqual('pending', self.release(proof)['status'])

    def test_outside_sheet(self):
        proof = self.prepare()
        self.trial(proof, 'unknown-step', 'L2', 'C', code=400)
        self.trial(proof, 'old-face', 'R1', 'A', code=400)
        disjoint = self.prepare(edition='D', front='LD', back='RD', table='DISJOINT')
        self.trial(disjoint, 'invalid-side-step', 'LD', 'B', code=400)
        self.trial(proof, 'boolean', 'L2', left=True, code=400)
        self.trial(proof, 'float', 'L2', right=25.0, code=400)
        self.post('/trial', code=400, proof_id=proof['proof_id'], trial_id='missing-edge',
                  face_id='L2', register_id='A', left_mm=20)
        for trial_id in ('unknown-step', 'old-face', 'invalid-side-step', 'boolean', 'float', 'missing-edge'):
            self.get('/trial', trial_id, code=404)
        self.assertEqual('pending', self.release(proof)['status'])

    def test_actual_register(self):
        proof = self.prepare()
        self.assertEqual(['A', 'B'], proof['common_registers'])
        for trial_id, face in (('lB', 'L2'), ('rB', 'R2')):
            trial = self.trial(proof, trial_id, face, 'B')
            self.assertEqual('B', trial['condition']['register_id'])
            self.assertEqual(trial, self.get('/trial', trial_id)['trial'])
        issued = self.release(proof)
        self.assertEqual('released', issued['status'])
        self.assertEqual('B', issued['order']['register_id'])
        self.trial(proof, 'lA', 'L2')
        self.trial(proof, 'rA', 'R2')
        self.assertEqual(issued, self.release(proof))
        self.assertEqual('A', self.release(proof, 'new-request')['order']['register_id'])

    def test_single_void(self):
        proof = self.prepare()
        self.trial(proof, 'lA', 'L2')
        original = self.trial(proof, 'r1', 'R2')
        self.trial(proof, 'r2', 'R2')
        self.void('missing', code=400)
        disposition = self.void('r1')
        self.assertEqual(disposition, self.void('r1'))
        self.void('r1', reason='changed reason', code=400)
        self.assertEqual({'trial': original, 'void': disposition}, self.get('/trial', 'r1'))
        self.assertIsNone(self.get('/trial', 'r2')['void'])
        released = self.release(proof)
        self.assertEqual('A', released['order']['register_id'])
        receipt = self.start_print(released['order'])['receipt']
        self.assertEqual('r2', receipt['back_trial_id'])

    def test_split_evidence(self):
        proof = self.prepare()
        empty = self.release(proof)
        self.assertEqual({'status': 'pending', 'request_id': 'job', 'order': None}, empty)
        self.trial(proof, 'lA', 'L2', 'A', left=15, right=30)
        self.trial(proof, 'rB', 'R2', 'B', left=30, right=20)
        split = self.release(proof)
        self.assertEqual(empty, split)
        self.assertEqual('not_found', self.get('/receipt', 'O-job', code=404)['status'])
        self.trial(proof, 'rA', 'R2', 'A', left=25, right=25)
        released = self.release(proof)
        self.assertEqual(('released', 'A'), (released['status'], released['order']['register_id']))
        start = self.start_print(released['order'])
        receipt = start['receipt']
        self.assertEqual(('started', 'A', 'lA', 'rA'),
                         (start['status'], receipt['register_id'], receipt['front_trial_id'], receipt['back_trial_id']))
        record_scenario('n5', {'registers': ['A', 'B'], 'initial_trials': ['L2/A', 'R2/B'],
                               'added_trial': 'R2/A'},
                        ['pending', 'pending', 'released'], [empty['status'], split['status'], released['status']],
                        ['A', 'lA', 'rA'], [receipt['register_id'], receipt['front_trial_id'], receipt['back_trial_id']],
                        ['trials/record.py', 'trials/evidence.py', 'release/qualification.py', 'printing/start.py'],
                        'Intersect the two faces’ observed register sets before and after adding the back A sample.')

    def test_keep_unchanged_face(self):
        old = self.prepare(edition='old', back='R1')
        self.trial(old, 'old-left', 'L2')
        self.trial(old, 'old-right', 'R1')
        self.assertEqual('released', self.release(old, 'old-order')['status'])
        new = self.prepare(edition='new')
        self.assertEqual('pending', self.release(new, 'new-order')['status'])
        self.trial(new, 'new-right', 'R2')
        result = self.release(new, 'new-order')
        self.assertEqual('A', result['order']['register_id'])
        receipt = self.start_print(result['order'])['receipt']
        self.assertEqual(('old-left', 'new-right'), (receipt['front_trial_id'], receipt['back_trial_id']))
        self.assertEqual(new['proof_id'], receipt['proof_id'])

    def test_conditions_isolate_table_and_paper(self):
        proof = self.prepare()
        self.trial(proof, 'original-left', 'L2')
        self.trial(proof, 'original-right', 'R2')
        steps = self.get('/register-tables', 'AB')['steps']
        self.post('/register-tables', table_id='AB-copy', steps=steps)
        other_table = self.prepare(table='AB-copy')
        self.post('/papers', paper_id='P600-copy', width_mm=600, print_left_mm=10,
                  print_right_mm=590, min_left_mm=15, min_right_mm=20)
        other_paper = self.prepare(paper='P600-copy')
        self.assertEqual('pending', self.release(other_table, 'other-table')['status'])
        self.assertEqual('pending', self.release(other_paper, 'other-paper')['status'])
        self.assertEqual('released', self.release(proof, 'original')['status'])

    def test_application_and_trial_conflicts(self):
        proof = self.prepare()
        original = self.trial(proof, 'fixed-trial', 'L2')
        self.assertEqual(original, self.trial(proof, 'fixed-trial', 'L2'))
        self.trial(proof, 'fixed-trial', 'L2', 'B', code=400)
        self.assertEqual(original, self.get('/trial', 'fixed-trial')['trial'])
        new = self.prepare(edition='E3')
        self.post('/release', code=400, request_id='job', edition_id='E3', proof_id=proof['proof_id'])
        first = self.release(proof)
        self.assertEqual('pending', first['status'])
        self.release(new, code=400)
        self.assertEqual(first, self.release(proof))
