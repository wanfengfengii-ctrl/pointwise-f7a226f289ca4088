from printing.workbench import initialize_workbench, load_sample, running_workbench
from tests.fixture import WorkbenchTestCase


class InitializationTests(WorkbenchTestCase):
    def test_initialize_preserves(self):
        revision = self.post('/faces', face_id='R3', side='back', left_mm=19, right_mm=570)
        self.post('/papers', paper_id='custom', width_mm=600, print_left_mm=10,
                  print_right_mm=590, min_left_mm=15, min_right_mm=20)
        self.post('/register-tables', table_id='custom-ab', steps=self.get('/register-tables', 'AB')['steps'])
        proof = self.prepare(back='R3', paper='custom', table='custom-ab')
        order = self.release_pair(proof)
        started = self.start_print(order)
        self.assertEqual('started', started['status'])
        self.assertEqual('songqiao-poster-v1', initialize_workbench(self.database, load_sample()))
        self.assertEqual(revision, self.get('/faces', 'R3'))
        self.assertEqual(proof, self.get('/proof', proof['proof_id']))
        self.assertEqual('custom', self.get('/papers', 'custom')['paper_id'])
        self.assertEqual('custom-ab', self.get('/register-tables', 'custom-ab')['table_id'])
        self.assertEqual(started, self.start_print(order))

    def test_conflicting_import_rolls_back_earlier_rows_and_marker(self):
        separate = self.database.with_name('conflicting.sqlite3')
        self.assertIsNone(initialize_workbench(separate))
        original_url = self.base_url
        try:
            with running_workbench(separate) as self.base_url:
                existing = self.post('/faces', face_id='L2', side='front', left_mm=21, right_mm=575)
                sample = load_sample()
                with self.assertRaisesRegex(ValueError, 'different revision'):
                    initialize_workbench(separate, sample)
                self.assertIsNone(initialize_workbench(separate))
                self.get('/faces', 'L1', code=404)
                self.get('/papers', 'P600', code=404)
                self.assertEqual(existing, self.get('/faces', 'L2'))
        finally:
            self.base_url = original_url
