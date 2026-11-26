from tests.fixture import WorkbenchTestCase, record_scenario


class PreparationTests(WorkbenchTestCase):
    def test_edge_allowance_at_limit(self):
        proof = self.prepare()
        actual = {side: entry['margins'] for side, entry in proof['settings']['A'].items()}
        expected = {'front': {'left_mm': 15, 'right_mm': 30},
                    'back': {'left_mm': 25, 'right_mm': 25}}
        self.assertEqual(expected, actual)
        self.assertEqual({'left_mm': 15, 'right_mm': 20}, proof['limits'])
        self.assertTrue(proof['settings']['A']['front']['can_trial'])
        self.assertTrue(proof['settings']['A']['back']['can_trial'])
        self.assertEqual(['A', 'B'], proof['common_registers'])
        self.assertEqual(proof, self.get('/proof', proof['proof_id']))
        record_scenario('n1', {'paper_width_mm': 600, 'print_area_mm': [10, 590],
                               'paper_limits_mm': [15, 20], 'front_bounds_mm': [20, 575],
                               'back_bounds_mm': [20, 570], 'register_offsets_mm': {'A': [-5, 5], 'B': [0, 0]}},
                        expected, actual, ['A', 'B'], proof['common_registers'],
                        ['setup/geometry.py', 'setup/margins.py', 'setup/proof_sheet.py'],
                        'Front A occupies [15,570]. Back A occupies [25,575] after mirroring. Compare each physical edge with limits 15 and 20 and repeat for B.')

    def test_inclusive_limit_and_adjacent_offsets(self):
        self.post('/register-tables', table_id='boundary', steps=[
            {'register_id': 'below', 'front_offset_mm': -6, 'back_offset_mm': 5},
            {'register_id': 'equal', 'front_offset_mm': -5, 'back_offset_mm': 5},
            {'register_id': 'above', 'front_offset_mm': -4, 'back_offset_mm': 5},
        ])
        proof = self.prepare(table='boundary')
        self.assertEqual(['above', 'equal'], proof['common_registers'])
        for register, left, allowed in (('below', 14, False), ('equal', 15, True), ('above', 16, True)):
            with self.subTest(register=register):
                front = proof['settings'][register]['front']
                self.assertEqual(left, front['margins']['left_mm'])
                self.assertEqual(allowed, front['can_trial'])
                self.assertEqual([] if allowed else ['left_below_limit'], front['reasons'])

    def test_wrong_face(self):
        rejected = self.post('/freeze', code=400, edition_id='E2', front_id='L2', back_id='L1')
        self.assertEqual('rejected', rejected['status'])
        self.get('/editions', 'E2', code=404)
        self.post('/freeze', code=400, edition_id='E2', front_id='L2', back_id='missing')
        self.get('/editions', 'E2', code=404)
        self.assertEqual({'edition_id': 'E2', 'front_id': 'L2', 'back_id': 'R2'},
                         self.post('/freeze', edition_id='E2', front_id='L2', back_id='R2'))

    def test_revision_history(self):
        old = self.prepare(edition='old', back='R1')
        new = self.prepare(edition='new')
        self.assertEqual(('L2', 'R1'), (old['front_id'], old['back_id']))
        self.assertEqual(('L2', 'R2'), (new['front_id'], new['back_id']))
        self.post('/freeze', code=400, edition_id='old', front_id='L2', back_id='R2')
        old_read = self.get('/editions', 'old')
        self.assertEqual(('L2', 'R1'), (old_read['front_id'], old_read['back_id']))
        self.assertEqual(21, self.get('/faces', 'R1')['left_mm'])
        self.assertEqual(old, self.get('/proof', old['proof_id']))

    def test_disjoint_registers(self):
        proof = self.prepare(front='LD', back='RD', table='DISJOINT')
        front = [step for step, sides in proof['settings'].items() if sides['front']['can_trial']]
        back = [step for step, sides in proof['settings'].items() if sides['back']['can_trial']]
        self.assertEqual(['A'], front)
        self.assertEqual(['B'], back)
        self.assertEqual([], proof['common_registers'])
        self.assertEqual(['no_common_register'], proof['reasons'])
        self.assertEqual(['left_below_limit'], proof['settings']['A']['back']['reasons'])
        self.assertEqual(['right_below_limit'], proof['settings']['B']['front']['reasons'])
        self.trial(proof, 'l', 'LD', 'A')
        self.trial(proof, 'r', 'RD', 'B')
        self.assertEqual({'status': 'pending', 'request_id': 'job', 'order': None}, self.release(proof))

    def test_unknown_proof_inputs_and_negative_projection(self):
        self.post('/freeze', edition_id='E2', front_id='L2', back_id='R2')
        for edition, paper, table in (('missing', 'P600', 'AB'), ('E2', 'missing', 'AB'),
                                      ('E2', 'P600', 'missing')):
            with self.subTest(edition=edition, paper=paper, table=table):
                self.post('/proof', code=400, edition_id=edition, paper_id=paper, table_id=table)
        self.post('/register-tables', table_id='out', steps=[
            {'register_id': 'A', 'front_offset_mm': -21, 'back_offset_mm': 5},
        ])
        proof = self.post('/proof', edition_id='E2', paper_id='P600', table_id='out')
        self.assertEqual({'left_mm': -1, 'right_mm': 46}, proof['settings']['A']['front']['margins'])
        self.assertEqual([], proof['common_registers'])
