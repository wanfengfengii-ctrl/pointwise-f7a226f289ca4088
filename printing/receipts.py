from dataclasses import dataclass
import sqlite3

from release.orders import PrintOrder
from release.qualification import WitnessPair


@dataclass(frozen=True)
class StartReceipt:
    start_id: str
    order_id: str
    confirmation_id: str
    proof_id: str
    register_id: str
    front_trial_id: str
    back_trial_id: str
    target_count: int | None = None


class ReceiptStore:
    schema = '''CREATE TABLE IF NOT EXISTS start_receipts (
        start_id TEXT PRIMARY KEY NOT NULL,
        order_id TEXT NOT NULL UNIQUE REFERENCES print_orders(order_id),
        confirmation_id TEXT NOT NULL UNIQUE,
        proof_id TEXT NOT NULL REFERENCES proof_sheets(proof_id),
        register_id TEXT NOT NULL,
        front_trial_id TEXT NOT NULL REFERENCES trials(trial_id),
        back_trial_id TEXT NOT NULL REFERENCES trials(trial_id),
        target_count TEXT,
        CHECK (front_trial_id <> back_trial_id)
    )'''
    columns = ('start_id, order_id, confirmation_id, proof_id, register_id, '
               'front_trial_id, back_trial_id, target_count')

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def add(self, order: PrintOrder, confirmation_id: str, pair: WitnessPair,
            target_count: int | None = None) -> StartReceipt:
        if pair.register_id != order.register_id:
            raise RuntimeError('receipt must use the published register')
        receipt = StartReceipt('S-' + order.order_id, order.order_id, confirmation_id,
                               order.proof_id, pair.register_id, pair.front.trial_id,
                               pair.back.trial_id, target_count)
        self.db.execute('INSERT INTO start_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (receipt.start_id, receipt.order_id, receipt.confirmation_id,
                         receipt.proof_id, receipt.register_id, receipt.front_trial_id,
                         receipt.back_trial_id,
                         None if target_count is None else str(target_count)))
        return receipt

    def _get(self, field: str, value: str) -> StartReceipt | None:
        row = self.db.execute(
            f'SELECT {self.columns} FROM start_receipts WHERE {field} = ?', (value,),
        ).fetchone()
        if row is None:
            return None
        return StartReceipt(*row[:-1], None if row[-1] is None else int(row[-1]))

    def get_by_order(self, order_id: str) -> StartReceipt | None:
        return self._get('order_id', order_id)

    def get_by_start(self, start_id: str) -> StartReceipt | None:
        return self._get('start_id', start_id)

    def get_by_confirmation(self, confirmation_id: str) -> StartReceipt | None:
        return self._get('confirmation_id', confirmation_id)
