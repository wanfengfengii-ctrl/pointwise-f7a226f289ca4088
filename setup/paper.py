from dataclasses import asdict, dataclass
import json
import sqlite3

from artwork.face import require_text


@dataclass(frozen=True)
class PaperSpec:
    paper_id: str
    width_mm: int
    print_left_mm: int
    print_right_mm: int
    min_left_mm: int
    min_right_mm: int

    def __post_init__(self):
        require_text(self.paper_id, 'paper_id')
        values = (self.width_mm, self.print_left_mm, self.print_right_mm,
                  self.min_left_mm, self.min_right_mm)
        if any(type(value) is not int for value in values):
            raise ValueError('paper dimensions must be integers in millimetres')
        if not 0 <= self.print_left_mm < self.print_right_mm <= self.width_mm:
            raise ValueError('print area must be a nonempty interval within the paper')
        if not (0 <= self.min_left_mm <= self.width_mm
                and 0 <= self.min_right_mm <= self.width_mm):
            raise ValueError('paper margin limits must be within the paper width')


class PaperStore:
    schema = '''CREATE TABLE IF NOT EXISTS papers (
        paper_id TEXT PRIMARY KEY NOT NULL,
        specification TEXT NOT NULL
    )'''

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, paper_id: str) -> PaperSpec | None:
        row = self.db.execute(
            'SELECT specification FROM papers WHERE paper_id = ?', (paper_id,),
        ).fetchone()
        return PaperSpec(**json.loads(row[0])) if row is not None else None

    def add(self, paper: PaperSpec) -> PaperSpec:
        existing = self.get(paper.paper_id)
        if existing is not None:
            if existing != paper:
                raise ValueError('paper_id already identifies a different paper specification')
            return existing
        self.db.execute('INSERT INTO papers VALUES (?, ?)',
                        (paper.paper_id, json.dumps(asdict(paper))))
        return paper


def register_paper(db, *, paper_id, width_mm, print_left_mm, print_right_mm,
                   min_left_mm, min_right_mm) -> PaperSpec:
    paper = PaperSpec(paper_id, width_mm, print_left_mm, print_right_mm,
                      min_left_mm, min_right_mm)
    return PaperStore(db).add(paper)
