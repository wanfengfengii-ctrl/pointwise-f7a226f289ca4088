from dataclasses import asdict, dataclass
import json
import sqlite3

from artwork.face import require_text


@dataclass(frozen=True)
class RegisterStep:
    register_id: str
    front_offset_mm: int
    back_offset_mm: int

    def __post_init__(self):
        require_text(self.register_id, 'register_id')
        if type(self.front_offset_mm) is not int or type(self.back_offset_mm) is not int:
            raise ValueError('register offsets must be signed integer millimetres')


@dataclass(frozen=True)
class RegisterTable:
    table_id: str
    steps: tuple[RegisterStep, ...]


class RegisterStore:
    schema = '''CREATE TABLE IF NOT EXISTS register_tables (
        table_id TEXT PRIMARY KEY NOT NULL,
        steps TEXT NOT NULL
    )'''

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, table_id: str) -> RegisterTable | None:
        row = self.db.execute(
            'SELECT steps FROM register_tables WHERE table_id = ?', (table_id,),
        ).fetchone()
        if row is None:
            return None
        return RegisterTable(table_id, tuple(RegisterStep(**step) for step in json.loads(row[0])))

    def add(self, table: RegisterTable) -> RegisterTable:
        existing = self.get(table.table_id)
        if existing is not None:
            if existing != table:
                raise ValueError('table_id already identifies a different register table')
            return existing
        self.db.execute('INSERT INTO register_tables VALUES (?, ?)',
                        (table.table_id, json.dumps([asdict(step) for step in table.steps])))
        return table


def register_table(db, *, table_id, steps) -> RegisterTable:
    require_text(table_id, 'table_id')
    if not isinstance(steps, list) or not steps:
        raise ValueError('steps must be a nonempty list')
    parsed = []
    fields = {'register_id', 'front_offset_mm', 'back_offset_mm'}
    for step in steps:
        if not isinstance(step, dict) or step.keys() != fields:
            raise ValueError('each step requires register_id, front_offset_mm and back_offset_mm')
        parsed.append(RegisterStep(**step))
    if len({step.register_id for step in parsed}) != len(parsed):
        raise ValueError('register ids must be unique within the table')
    table = RegisterTable(table_id, tuple(sorted(parsed, key=lambda step: step.register_id)))
    return RegisterStore(db).add(table)
