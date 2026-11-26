from dataclasses import dataclass
import sqlite3

from release.requests import ReleaseRequest


@dataclass(frozen=True)
class PrintOrder:
    order_id: str
    request_id: str
    edition_id: str
    proof_id: str
    register_id: str
    started: bool


class OrderStore:
    schema = '''CREATE TABLE IF NOT EXISTS print_orders (
        order_id TEXT PRIMARY KEY NOT NULL,
        request_id TEXT NOT NULL UNIQUE REFERENCES release_requests(request_id),
        edition_id TEXT NOT NULL REFERENCES editions(edition_id),
        proof_id TEXT NOT NULL REFERENCES proof_sheets(proof_id),
        register_id TEXT NOT NULL,
        started INTEGER NOT NULL CHECK (started IN (0, 1))
    )'''
    columns = 'order_id, request_id, edition_id, proof_id, register_id, started'

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    @staticmethod
    def _order(row) -> PrintOrder | None:
        if row is None:
            return None
        return PrintOrder(*row[:-1], bool(row[-1]))

    def get(self, order_id: str) -> PrintOrder | None:
        row = self.db.execute(
            f'SELECT {self.columns} FROM print_orders WHERE order_id = ?', (order_id,),
        ).fetchone()
        return self._order(row)

    def get_for_request(self, request_id: str) -> PrintOrder | None:
        row = self.db.execute(
            f'SELECT {self.columns} FROM print_orders WHERE request_id = ?', (request_id,),
        ).fetchone()
        return self._order(row)

    def add(self, order: PrintOrder) -> None:
        self.db.execute('INSERT INTO print_orders VALUES (?, ?, ?, ?, ?, ?)',
                        (order.order_id, order.request_id, order.edition_id,
                         order.proof_id, order.register_id, order.started))


def create_order(db, request: ReleaseRequest, register_id: str) -> PrintOrder:
    order = PrintOrder('O-' + request.request_id, request.request_id, request.edition_id,
                       request.proof_id, register_id, False)
    OrderStore(db).add(order)
    return order


def mark_order_started(db, order_id: str) -> None:
    result = db.execute('UPDATE print_orders SET started = 1 WHERE order_id = ? AND started = 0',
                        (order_id,))
    if result.rowcount != 1:
        raise RuntimeError('expected exactly one unstarted order')
