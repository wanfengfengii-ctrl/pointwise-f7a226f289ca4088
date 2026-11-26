import argparse
from contextlib import contextmanager, closing
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
from inspect import signature
from functools import partial

from artwork.edition import EditionStore, freeze_edition
from artwork.face import require_text
from artwork.intake import register_face
from artwork.revisions import RevisionStore
from printing.completion import CompletionStore, finish_print
from printing.handover import read_handover
from printing.press_run import (PressResponse, PressTurnNotFound, TurnStore, feed_turn,
                                open_turn, read_turn, yield_turn)
from printing.receipts import ReceiptStore, StartReceipt
from printing.start import confirm_start
from release.issue import issue_order
from release.orders import OrderStore
from release.requests import RequestStore
from setup.paper import PaperStore, register_paper
from setup.proof_sheet import ProofStore, build_proof_sheet
from setup.registers import RegisterStore, register_table
from trials.disposition import VoidStore, void_trial
from trials.record import TrialStore, record_trial


SAMPLES = Path(__file__).resolve().parents[1] / 'samples'
STORES = (RevisionStore, EditionStore, PaperStore, RegisterStore, ProofStore,
          TrialStore, VoidStore, RequestStore, OrderStore, ReceiptStore, CompletionStore,
          TurnStore)
POST_ROUTES = {
    '/faces': register_face,
    '/papers': register_paper,
    '/register-tables': register_table,
    '/freeze': freeze_edition,
    '/proof': build_proof_sheet,
    '/trial': record_trial,
    '/void': void_trial,
    '/release': issue_order,
    '/start': confirm_start,
    '/finish': finish_print,
    '/press-turn': open_turn,
    '/press-feed': feed_turn,
    '/press-yield': yield_turn,
}
GET_STORES = {'/faces': RevisionStore, '/editions': EditionStore, '/papers': PaperStore,
              '/register-tables': RegisterStore, '/proof': ProofStore}


@contextmanager
def transaction(database, *, write):
    with closing(sqlite3.connect(database, timeout=5)) as db:
        db.execute('PRAGMA foreign_keys = ON')
        with db:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db


def load_sample():
    return json.loads((SAMPLES / 'references.json').read_text(encoding='utf-8'))


def initialize_workbench(database, sample=None) -> str | None:
    with transaction(database, write=True) as db:
        for store in STORES:
            db.execute(store.schema)
        columns = {row[1] for row in db.execute('PRAGMA table_info(start_receipts)')}
        if 'target_count' not in columns:
            db.execute('ALTER TABLE start_receipts ADD COLUMN target_count TEXT')
        db.execute('''CREATE TABLE IF NOT EXISTS sample_import (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1), version TEXT NOT NULL
        )''')
        row = db.execute('SELECT version FROM sample_import WHERE singleton = 1').fetchone()
        current = row[0] if row is not None else None
        if sample is None:
            return current
        version = require_text(sample['version'], 'sample version')
        if current is not None and current != version:
            raise ValueError('a different sample version has already been initialized')
        for key, register in (('faces', register_face), ('papers', register_paper),
                              ('register_tables', register_table)):
            for item in sample[key]:
                register(db, **item)
        if current is None:
            db.execute('INSERT INTO sample_import VALUES (1, ?)', (version,))
        return version


def _json_default(value):
    if is_dataclass(value):
        data = asdict(value)
        receipt = getattr(value, 'receipt', None)
        if receipt is not None and type(receipt) is StartReceipt and receipt.target_count is None:
            data['receipt'].pop('target_count', None)
        if type(value).__name__ == 'HandoverResult' and value.press_turns is None:
            data.pop('press_turns', None)
        return data
    raise TypeError(f'cannot serialize {type(value).__name__}')


def _read_resource(db, path, identity):
    if path == '/receipt':
        result = read_handover(db, identity)
        return (404 if result.status == 'not_found' else 200), result
    if path == '/trial':
        trial = TrialStore(db).get(identity)
        if trial is not None:
            return 200, {'trial': trial, 'void': VoidStore(db).get(identity)}
    else:
        value = GET_STORES[path](db).get(identity)
        if value is not None:
            return 200, value
    return 404, {'status': 'not_found'}


class WorkbenchHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, result):
        body = json.dumps(result, default=_json_default, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        if self.headers.get_content_type() != 'application/json':
            raise ValueError('Content-Type must be application/json')
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or self.headers.get('Transfer-Encoding') is not None:
            raise ValueError('request requires one Content-Length and no Transfer-Encoding')
        if not lengths[0].isascii() or not lengths[0].isdecimal():
            raise ValueError('invalid Content-Length')
        length = int(lengths[0])
        if not 0 < length <= 65536:
            raise ValueError('request body must contain 1–65536 bytes')
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError('incomplete request body')
        data = json.loads(body.decode('utf-8'), object_pairs_hook=self._unique_fields)
        if not isinstance(data, dict):
            raise ValueError('request body must be a JSON object')
        return data

    @staticmethod
    def _unique_fields(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError(f'duplicate JSON field: {name}')
            result[name] = value
        return result

    def _post(self, target):
        endpoint = POST_ROUTES.get(target.path)
        if endpoint is None:
            return 404, {'status': 'not_found'}
        if target.query:
            raise ValueError('POST parameters belong in the JSON body')
        data = self._body()
        with transaction(self.server.database, write=True) as db:
            try:
                signature(endpoint).bind(db, **data)
            except TypeError as exc:
                raise ValueError(str(exc)) from exc
            result = endpoint(db, **data)
        if isinstance(result, PressResponse):
            return result.http_status, result.body
        if endpoint is confirm_start and result.status == 'not_found':
            return 404, result
        return 200, result

    def _get(self, target):
        if target.path == '/press-turn':
            query = parse_qs(target.query, keep_blank_values=True, strict_parsing=True,
                             errors='strict', max_num_fields=8)
            if query.keys() != {'id'} or len(query['id']) != 1:
                raise ValueError('GET requires exactly one id query parameter')
            turn_id = require_text(query['id'][0], 'id')
            with transaction(self.server.database, write=False) as db:
                result = read_turn(db, turn_id)
            return result.http_status, result.body
        if target.path not in GET_STORES and target.path not in ('/receipt', '/trial'):
            return 404, {'status': 'not_found'}
        query = parse_qs(target.query, keep_blank_values=True, strict_parsing=True,
                         errors='strict', max_num_fields=8)
        if query.keys() != {'id'} or len(query['id']) != 1:
            raise ValueError('GET requires exactly one id query parameter')
        identity = require_text(query['id'][0], 'id')
        with transaction(self.server.database, write=False) as db:
            return _read_resource(db, target.path, identity)

    def _handle(self, dispatch):
        try:
            status, result = dispatch(urlsplit(self.path))
        except PressTurnNotFound as exc:
            status, result = 404, {'status': 'not_found', 'error': str(exc)}
        except (ValueError, RecursionError) as exc:
            status, result = 400, {'status': 'rejected', 'error': str(exc)}
        except sqlite3.OperationalError as exc:
            code = getattr(exc, 'sqlite_errorcode', 0) & 255
            if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                status, result = 503, {'status': 'unavailable', 'error': 'database busy'}
            else:
                logging.exception('Workbench database operation failed')
                status, result = 500, {'status': 'internal_error'}
        except Exception:
            logging.exception('Workbench request failed')
            status, result = 500, {'status': 'internal_error'}
        self._send_json(status, result)

    def do_POST(self):
        self._handle(self._post)

    def do_GET(self):
        self._handle(self._get)

    def log_message(self, fmt, *args):
        if self.server.access_log:
            super().log_message(fmt, *args)


class WorkbenchServer(ThreadingHTTPServer):
    def __init__(self, database, port, access_log):
        self.database = database
        self.access_log = access_log
        super().__init__(('127.0.0.1', port), WorkbenchHandler)


def create_server(database, port=0, *, access_log=False):
    return WorkbenchServer(database, port, access_log)


@contextmanager
def running_workbench(database):
    with create_server(database) as server:
        worker = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        worker.start()
        try:
            host, port = server.server_address
            yield f'http://{host}:{port}'
        finally:
            server.shutdown()
            worker.join()


def _lookup(value, path):
    for key in path.split('.'):
        value = value[key]
    return value


def _play_events(base_url, events):
    saved = {}
    for event in events:
        data = {key: _lookup(saved, value['$ref']) if isinstance(value, dict) else value
                for key, value in event['data'].items()}
        method = event['method']
        url = base_url + event['path']
        if method == 'GET':
            request = Request(url + '?' + urlencode(data), method='GET')
        elif method == 'POST':
            request = Request(url, json.dumps(data).encode('utf-8'),
                              {'Content-Type': 'application/json'}, method='POST')
        else:
            raise ValueError(f'unsupported demo method: {method}')
        with urlopen(request, timeout=6) as response:
            result = json.load(response)
        name = event['name']
        for path, expected in event['expect'].items():
            try:
                actual = _lookup(result, path)
            except (KeyError, TypeError) as exc:
                raise AssertionError(f'{name}: missing response field {path}') from exc
            if actual != expected:
                raise AssertionError(f'{name}: {path}: expected {expected!r}, received {actual!r}')
        saved[name] = result
        print(json.dumps({'event': name, 'result': result}, ensure_ascii=False, sort_keys=True))


def _demo():
    try:
        events = json.loads((SAMPLES / 'events.json').read_text(encoding='utf-8'))
        with TemporaryDirectory(prefix='songqiao-demo-') as directory:
            database = Path(directory) / 'workbench.sqlite3'
            initialize_workbench(database, load_sample())
            with running_workbench(database) as base_url:
                try:
                    _play_events(base_url, events)
                except AssertionError as exc:
                    print(f'POINTWISE_BUSINESS_FAILURE {exc}', file=sys.stderr)
                    return 1
                except (URLError, OSError, ValueError, KeyError, TypeError) as exc:
                    print(f'DEMO_CALL_ERROR {exc}', file=sys.stderr)
                    return 2
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        print(f'DEMO_STARTUP_ERROR {exc}', file=sys.stderr)
        return 3
    return 0


def _http_call(base_url):
    def request(method, path, payload=None):
        if method == 'GET':
            http_request = Request(base_url + path + '?' + urlencode(payload), method='GET')
        else:
            http_request = Request(base_url + path, json.dumps(payload).encode('utf-8'),
                                   {'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(http_request, timeout=8) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            with response:
                return response.code, json.load(response)

    def post(path, **data):
        return request('POST', path, data)

    def get(path, identity):
        return request('GET', path, {'id': identity})

    return post, get


def _press_demo():
    try:
        from printing.press_device import open_press
        from printing.press_exercise import run_press_wheel
        with TemporaryDirectory(prefix='songqiao-press-demo-') as directory:
            database = Path(directory) / 'workbench.sqlite3'
            initialize_workbench(database, load_sample())
            with running_workbench(database) as base_url:
                post, get = _http_call(base_url)
                open_device = partial(open_press, database)

                def emit(event):
                    print(json.dumps(event, ensure_ascii=False, sort_keys=True))

                try:
                    for mode in ('drain', 'cutover'):
                        result = run_press_wheel(post, get, open_device, mode=mode,
                                                 emit=emit, suffix='-' + mode)
                        print(json.dumps({'wheel': mode, 'result': result},
                                         ensure_ascii=False, sort_keys=True))
                except AssertionError as exc:
                    print(f'POINTWISE_BUSINESS_FAILURE {exc}', file=sys.stderr)
                    return 1
                except (URLError, OSError, ValueError, KeyError, TypeError) as exc:
                    print(f'DEMO_CALL_ERROR {exc}', file=sys.stderr)
                    return 2
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        print(f'DEMO_STARTUP_ERROR {exc}', file=sys.stderr)
        return 3
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Songqiao duplex poster workbench')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('demo')
    commands.add_parser('press-demo')
    init = commands.add_parser('init')
    serve = commands.add_parser('serve')
    for command in (init, serve):
        command.add_argument('--db', required=True, type=Path)
        command.add_argument('--sample', action='store_true')
    serve.add_argument('--port', type=int, default=8080)
    args = parser.parse_args(argv)
    if args.command == 'demo':
        return _demo()
    if args.command == 'press-demo':
        return _press_demo()
    if args.command == 'serve' and not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    try:
        version = initialize_workbench(args.db, load_sample() if args.sample else None)
        if args.command == 'init':
            print(json.dumps({'sample_version': version}))
        else:
            with create_server(args.db, args.port, access_log=True) as server:
                host, port = server.server_address
                print(f'http://{host}:{port}', flush=True)
                server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        print(f'WORKBENCH_STARTUP_ERROR {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
