from dataclasses import dataclass
import sqlite3

from artwork.face import require_text
from trials.record import TrialStore


@dataclass(frozen=True)
class VoidRecord:
    trial_id: str
    reason: str


class VoidStore:
    schema = '''CREATE TABLE IF NOT EXISTS void_trials (
        trial_id TEXT PRIMARY KEY NOT NULL REFERENCES trials(trial_id),
        reason TEXT NOT NULL
    )'''

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, trial_id: str) -> VoidRecord | None:
        row = self.db.execute(
            'SELECT reason FROM void_trials WHERE trial_id = ?', (trial_id,),
        ).fetchone()
        return VoidRecord(trial_id, row[0]) if row is not None else None

    def is_voided(self, trial_id: str) -> bool:
        return self.get(trial_id) is not None

    def add(self, record: VoidRecord) -> VoidRecord:
        existing = self.get(record.trial_id)
        if existing is not None:
            if existing != record:
                raise ValueError('trial is already voided with a different reason')
            return existing
        self.db.execute('INSERT INTO void_trials VALUES (?, ?)', (record.trial_id, record.reason))
        return record


def void_trial(db, *, trial_id, reason) -> VoidRecord:
    record = VoidRecord(require_text(trial_id, 'trial_id'), require_text(reason, 'reason'))
    if TrialStore(db).get(trial_id) is None:
        raise ValueError('unknown trial_id')
    return VoidStore(db).add(record)
