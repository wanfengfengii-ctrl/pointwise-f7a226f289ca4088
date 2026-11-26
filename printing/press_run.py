"""Segmented press runs: occupy the shared press, feed paper once per turn and yield."""
from dataclasses import dataclass
import sqlite3

from artwork.face import require_text
from printing.press_device import open_press
from printing.receipts import ReceiptStore


class PressTurnNotFound(LookupError):
    """Raised when a turn id or start id does not point at a stored record."""


@dataclass(frozen=True)
class PressResponse:
    http_status: int
    body: dict


@dataclass(frozen=True)
class PressTurn:
    status: str
    turn_id: str
    start_id: str
    start_counter: int
    end_counter: int | None
    generation: int
    slot: int
    feed_count: int | None
    feed_outcome: str | None
    feed_http: int | None
    seq: int

    def record(self) -> dict:
        return {
            'status': self.status,
            'turn_id': self.turn_id,
            'start_id': self.start_id,
            'start_counter': self.start_counter,
            'end_counter': self.end_counter,
            'count': None if self.end_counter is None else self.end_counter - self.start_counter,
        }


class TurnStore:
    schema = '''CREATE TABLE IF NOT EXISTS press_turns (
        turn_id TEXT PRIMARY KEY NOT NULL,
        start_id TEXT NOT NULL REFERENCES start_receipts(start_id),
        seq INTEGER NOT NULL UNIQUE,
        start_counter INTEGER NOT NULL,
        end_counter INTEGER,
        generation INTEGER NOT NULL,
        slot INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('active', 'yielding', 'yielded')),
        feed_count INTEGER,
        feed_outcome TEXT,
        feed_http INTEGER,
        CHECK (status = 'yielded' OR end_counter IS NULL OR status = 'yielding')
    )'''

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, turn_id: str) -> PressTurn | None:
        row = self.db.execute(
            'SELECT status, turn_id, start_id, start_counter, end_counter, generation, slot, '
            'feed_count, feed_outcome, feed_http, seq FROM press_turns WHERE turn_id = ?',
            (turn_id,),
        ).fetchone()
        return PressTurn(*row) if row is not None else None

    def next_seq(self) -> int:
        row = self.db.execute('SELECT COALESCE(MAX(seq), 0) + 1 FROM press_turns').fetchone()
        return row[0]

    def find_open(self) -> PressTurn | None:
        row = self.db.execute(
            'SELECT status, turn_id, start_id, start_counter, end_counter, generation, slot, '
            'feed_count, feed_outcome, feed_http, seq FROM press_turns '
            "WHERE status <> 'yielded' ORDER BY seq"
        ).fetchone()
        return PressTurn(*row) if row is not None else None

    def insert(self, turn: PressTurn) -> None:
        self.db.execute(
            'INSERT INTO press_turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (turn.turn_id, turn.start_id, turn.seq, turn.start_counter, turn.end_counter,
             turn.generation, turn.slot, turn.status, turn.feed_count, turn.feed_outcome,
             turn.feed_http),
        )

    def set_status(self, turn_id: str, status: str, end_counter: int | None) -> None:
        self.db.execute('UPDATE press_turns SET status = ?, end_counter = ? WHERE turn_id = ?',
                        (status, end_counter, turn_id))

    def set_feed(self, turn_id: str, count: int, outcome: str, http_status: int) -> None:
        self.db.execute(
            'UPDATE press_turns SET feed_count = ?, feed_outcome = ?, feed_http = ? WHERE turn_id = ?',
            (count, outcome, http_status, turn_id),
        )

    def confirmed_turns(self, start_id: str) -> list[PressTurn]:
        rows = self.db.execute(
            'SELECT status, turn_id, start_id, start_counter, end_counter, generation, slot, '
            'feed_count, feed_outcome, feed_http, seq FROM press_turns '
            "WHERE start_id = ? AND status = 'yielded' ORDER BY seq",
            (start_id,),
        ).fetchall()
        return [PressTurn(*row) for row in rows]


def _press_path(db: sqlite3.Connection) -> str:
    return db.execute('PRAGMA database_list').fetchone()[2]


def confirmed_count(db: sqlite3.Connection, start_id: str) -> int:
    return sum(turn.end_counter - turn.start_counter
               for turn in TurnStore(db).confirmed_turns(start_id))


def _require_segmented_receipt(db: sqlite3.Connection, start_id: str):
    from printing.completion import CompletionStore
    receipt = ReceiptStore(db).get_by_start(start_id)
    if receipt is None:
        raise PressTurnNotFound(f'unknown start_id: {start_id}')
    if receipt.target_count is None:
        raise ValueError('only segmented print orders can occupy the press')
    if CompletionStore(db).get(start_id) is not None:
        raise ValueError('print order has already been sealed')
    return receipt


def open_turn(db: sqlite3.Connection, *, start_id: str, turn_id: str) -> PressResponse:
    require_text(start_id, 'start_id')
    require_text(turn_id, 'turn_id')
    store = TurnStore(db)
    existing = store.get(turn_id)
    if existing is not None:
        if existing.start_id != start_id:
            raise ValueError('turn_id already belongs to another start receipt')
        return PressResponse(200, existing.record())
    _require_segmented_receipt(db, start_id)
    occupied = store.find_open()
    if occupied is not None:
        raise ValueError(f'press is occupied by turn {occupied.turn_id}')
    with open_press(_press_path(db)) as press:
        reading = press.read()
    turn = PressTurn('active', turn_id, start_id, reading.counter, None, reading.generation,
                     reading.drained_through + 1, None, None, None, store.next_seq())
    store.insert(turn)
    return PressResponse(200, turn.record())


def _feed_body(turn: PressTurn, count: int) -> dict:
    return {'status': turn.feed_outcome, 'turn_id': turn.turn_id, 'count': count}


def feed_turn(db: sqlite3.Connection, *, turn_id: str, count: int) -> PressResponse:
    require_text(turn_id, 'turn_id')
    if type(count) is not int or count < 1:
        raise ValueError('count must be a positive integer')
    store = TurnStore(db)
    turn = store.get(turn_id)
    if turn is None:
        raise PressTurnNotFound(f'unknown turn_id: {turn_id}')
    if turn.feed_count is not None:
        if turn.feed_count != count:
            raise ValueError('an accepted feed cannot be changed to a different count')
        # Replaying the same feed may deliver the original command, but never a second one.
        with open_press(_press_path(db)) as press:
            try:
                press.submit(turn.generation, turn.slot, count)
            except TimeoutError:
                pass
        return PressResponse(turn.feed_http, _feed_body(turn, count))
    if turn.status == 'yielded':
        raise ValueError('turn has already been yielded')
    if turn.status == 'yielding':
        raise ValueError('handover has started; the first feed is no longer accepted')
    receipt = _require_segmented_receipt(db, turn.start_id)
    remaining = receipt.target_count - confirmed_count(db, turn.start_id)
    if count > remaining:
        raise ValueError(f'feed count {count} exceeds the order remainder {remaining}')
    with open_press(_press_path(db)) as press:
        try:
            outcome = press.submit(turn.generation, turn.slot, count)
        except TimeoutError:
            store.set_feed(turn_id, count, 'pending', 202)
            turn = store.get(turn_id)
            return PressResponse(202, _feed_body(turn, count))
    if outcome != 'accepted':
        raise RuntimeError(f'press rejected the first feed: {outcome}')
    store.set_feed(turn_id, count, 'accepted', 200)
    turn = store.get(turn_id)
    return PressResponse(200, _feed_body(turn, count))


def yield_turn(db: sqlite3.Connection, *, turn_id: str) -> PressResponse:
    require_text(turn_id, 'turn_id')
    store = TurnStore(db)
    turn = store.get(turn_id)
    if turn is None:
        raise PressTurnNotFound(f'unknown turn_id: {turn_id}')
    if turn.status == 'yielded':
        return PressResponse(200, turn.record())
    with open_press(_press_path(db)) as press:
        reading = press.read()
        if reading.generation > turn.generation:
            # A cutover already happened: the old generation can no longer produce sheets.
            end_counter = turn.end_counter if turn.end_counter is not None else reading.counter
            store.set_status(turn_id, 'yielded', end_counter)
            return PressResponse(200, store.get(turn_id).record())
        in_flight = (turn.feed_count is not None
                     and reading.drained_through < turn.slot
                     and reading.generation == turn.generation)
        if in_flight:
            if turn.status == 'active':
                # First handover call only reports the unverified feed; nothing is cut yet.
                store.set_status(turn_id, 'yielding', None)
                return PressResponse(202, store.get(turn_id).record())
            try:
                press.advance(turn.generation)
            except TimeoutError:
                # The advance is committed before the reply is lost.
                latest = press.read()
                store.set_status(turn_id, 'yielding', latest.counter)
                return PressResponse(202, store.get(turn_id).record())
            reading = press.read()
        store.set_status(turn_id, 'yielded', reading.counter)
        return PressResponse(200, store.get(turn_id).record())


def read_turn(db: sqlite3.Connection, turn_id: str) -> PressResponse:
    require_text(turn_id, 'turn_id')
    turn = TurnStore(db).get(turn_id)
    if turn is None:
        raise PressTurnNotFound(f'unknown turn_id: {turn_id}')
    return PressResponse(200, turn.record())


def turn_records_for_order(db: sqlite3.Connection, start_id: str) -> list[dict]:
    return [turn.record() for turn in TurnStore(db).confirmed_turns(start_id)]
