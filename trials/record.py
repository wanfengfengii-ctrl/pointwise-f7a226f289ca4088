from dataclasses import asdict, dataclass
import json
import sqlite3

from artwork.face import require_text
from setup.margins import EdgeMargins
from setup.proof_sheet import ProofStore
from trials.conditions import TrialCondition, resolve_trial_condition
from trials.measurements import MeasurementResult, evaluate_measurements


@dataclass(frozen=True)
class TrialRecord:
    trial_id: str
    proof_id: str
    condition: TrialCondition
    result: MeasurementResult


class TrialStore:
    schema = '''CREATE TABLE IF NOT EXISTS trials (
        trial_id TEXT PRIMARY KEY NOT NULL,
        proof_id TEXT NOT NULL REFERENCES proof_sheets(proof_id),
        face_id TEXT NOT NULL REFERENCES face_revisions(face_id),
        paper_id TEXT NOT NULL REFERENCES papers(paper_id),
        table_id TEXT NOT NULL REFERENCES register_tables(table_id),
        register_id TEXT NOT NULL,
        measurement TEXT NOT NULL
    )'''
    columns = 'trial_id, proof_id, face_id, paper_id, table_id, register_id, measurement'

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    @staticmethod
    def _record(row) -> TrialRecord:
        trial_id, proof_id, face_id, paper_id, table_id, register_id, measurement = row
        data = json.loads(measurement)
        return TrialRecord(trial_id, proof_id, TrialCondition(face_id, paper_id, table_id, register_id),
                           MeasurementResult(EdgeMargins(**data['measured']), data['passed'],
                                             tuple(data['reasons'])))

    def get(self, trial_id: str) -> TrialRecord | None:
        row = self.db.execute(
            f'SELECT {self.columns} FROM trials WHERE trial_id = ?', (trial_id,),
        ).fetchone()
        return self._record(row) if row is not None else None

    def for_condition(self, condition: TrialCondition) -> tuple[TrialRecord, ...]:
        rows = self.db.execute(
            f'''SELECT {self.columns} FROM trials
                WHERE face_id = ? AND paper_id = ? AND table_id = ? AND register_id = ?
                ORDER BY trial_id''',
            (condition.face_id, condition.paper_id, condition.table_id, condition.register_id),
        )
        return tuple(self._record(row) for row in rows)

    def add(self, trial: TrialRecord) -> TrialRecord:
        existing = self.get(trial.trial_id)
        if existing is not None:
            if existing != trial:
                raise ValueError('trial_id already identifies a different trial')
            return existing
        condition = trial.condition
        self.db.execute(
            'INSERT INTO trials VALUES (?, ?, ?, ?, ?, ?, ?)',
            (trial.trial_id, trial.proof_id, condition.face_id, condition.paper_id,
             condition.table_id, condition.register_id, json.dumps(asdict(trial.result))),
        )
        return trial


def record_trial(db, *, proof_id, trial_id, face_id, register_id, left_mm, right_mm) -> TrialRecord:
    require_text(trial_id, 'trial_id')
    require_text(face_id, 'face_id')
    require_text(register_id, 'register_id')
    proof = ProofStore(db).get(require_text(proof_id, 'proof_id'))
    if proof is None:
        raise ValueError('unknown proof_id')
    condition = resolve_trial_condition(proof, face_id, register_id)
    result = evaluate_measurements(left_mm, right_mm, proof.limits)
    return TrialStore(db).add(TrialRecord(trial_id, proof.proof_id, condition, result))
