import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from printing.workbench import initialize_workbench, load_sample, running_workbench


class WorkbenchTestCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='songqiao-test-')
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / 'workbench.sqlite3'
        initialize_workbench(self.database, load_sample())
        self.server = None
        self.addCleanup(self.stop)
        self.restart()

    def stop(self):
        if self.server is not None:
            self.server.__exit__(None, None, None)
            self.server = None

    def restart(self):
        self.stop()
        server = running_workbench(self.database)
        self.base_url = server.__enter__()
        self.server = server

    def _send(self, url, payload=None):
        if payload is None:
            request = Request(self.base_url + url)
        else:
            request = Request(self.base_url + url, json.dumps(payload).encode('utf-8'),
                              {'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=8) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            with response:
                return response.code, json.load(response)

    def post(self, path, *, code=200, **data):
        status, result = self._send(path, data)
        self.assertEqual(code, status, result)
        return result

    def get(self, path, identity, *, code=200):
        status, result = self._send(path + '?' + urlencode({'id': identity}))
        self.assertEqual(code, status, result)
        return result

    def prepare(self, edition='E2', front='L2', back='R2', table='AB', paper='P600'):
        self.post('/freeze', edition_id=edition, front_id=front, back_id=back)
        return self.post('/proof', edition_id=edition, paper_id=paper, table_id=table)

    def trial(self, proof, trial_id, face, register='A', *, left=20, right=25, code=200):
        return self.post('/trial', code=code, proof_id=proof['proof_id'], trial_id=trial_id,
                         face_id=face, register_id=register, left_mm=left, right_mm=right)

    def release(self, proof, request='job', *, code=200):
        return self.post('/release', code=code, request_id=request,
                         edition_id=proof['edition_id'], proof_id=proof['proof_id'])

    def void(self, trial_id, *, reason='sample damaged', code=200):
        return self.post('/void', code=code, trial_id=trial_id, reason=reason)

    def start_print(self, order, *, confirmation='mount', code=200):
        return self.post('/start', code=code, order_id=order['order_id'],
                         confirmation_id=confirmation)

    def release_pair(self, proof, request='job', *, prefix=''):
        self.trial(proof, prefix + 'lA', proof['front_id'])
        self.trial(proof, prefix + 'rA', proof['back_id'])
        result = self.release(proof, request)
        self.assertEqual('released', result['status'], result)
        self.assertEqual('A', result['order']['register_id'])
        return result['order']


def record_scenario(case_id, inputs, expected, actual, downstream_expected,
                    downstream_actual, code_paths, oracle):
    result = {'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
              'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
              'code_paths': code_paths, 'oracle': oracle}
    print('POINTWISE_SCENARIO ' + json.dumps(result, ensure_ascii=False, sort_keys=True))
