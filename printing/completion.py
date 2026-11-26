from dataclasses import dataclass
import sqlite3

from artwork.face import require_text
from printing.press_run import TurnStore, confirmed_count
from printing.receipts import ReceiptStore


@dataclass(frozen=True)
class Completion:
    start_id: str
    good_count: int
    waste_count: int


class CompletionStore:
    schema = '''CREATE TABLE IF NOT EXISTS completions (
        start_id TEXT PRIMARY KEY NOT NULL REFERENCES start_receipts(start_id),
        good_count TEXT NOT NULL,
        waste_count TEXT NOT NULL
    )'''

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, start_id: str) -> Completion | None:
        row = self.db.execute(
            'SELECT good_count, waste_count FROM completions WHERE start_id = ?', (start_id,),
        ).fetchone()
        return Completion(start_id, int(row[0]), int(row[1])) if row is not None else None

    def add(self, completion: Completion) -> Completion:
        existing = self.get(completion.start_id)
        if existing is not None:
            if existing != completion:
                raise ValueError('completion is already sealed with different counts')
            return existing
        self.db.execute('INSERT INTO completions VALUES (?, ?, ?)',
                        (completion.start_id, str(completion.good_count), str(completion.waste_count)))
        return completion


def validate_counts(good_count: int, waste_count: int) -> None:
    if any(type(count) is not int or count < 0 for count in (good_count, waste_count)):
        raise ValueError('print counts must be nonnegative integers')


def finish_print(db, *, start_id, good_count, waste_count) -> Completion:
    require_text(start_id, 'start_id')
    validate_counts(good_count, waste_count)
    receipt = ReceiptStore(db).get_by_start(start_id)
    if receipt is None:
        raise ValueError('completion requires an existing start receipt')
    if receipt.target_count is not None:
        open_turn = TurnStore(db).find_open()
        if open_turn is not None and open_turn.start_id == start_id:
            raise ValueError('a press turn is still occupying the press')
        actual = confirmed_count(db, start_id)
        if actual != receipt.target_count:
            raise ValueError(
                f'confirmed press count {actual} has not reached target {receipt.target_count}')
        if good_count + waste_count != actual:
            raise ValueError(
                f'good and waste counts must sum to the confirmed press count {actual}')
    return CompletionStore(db).add(Completion(start_id, good_count, waste_count))
