from dataclasses import dataclass
import sqlite3

from artwork.face import FaceSide, require_text
from artwork.revisions import RevisionStore


@dataclass(frozen=True)
class Edition:
    edition_id: str
    front_id: str
    back_id: str


class EditionStore:
    schema = '''CREATE TABLE IF NOT EXISTS editions (
        edition_id TEXT PRIMARY KEY NOT NULL,
        front_id TEXT NOT NULL REFERENCES face_revisions(face_id),
        back_id TEXT NOT NULL REFERENCES face_revisions(face_id),
        CHECK (front_id <> back_id)
    )'''

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, edition_id: str) -> Edition | None:
        row = self.db.execute(
            'SELECT front_id, back_id FROM editions WHERE edition_id = ?',
            (edition_id,),
        ).fetchone()
        return Edition(edition_id, *row) if row is not None else None

    def add(self, edition: Edition) -> None:
        self.db.execute(
            'INSERT INTO editions (edition_id, front_id, back_id) VALUES (?, ?, ?)',
            (edition.edition_id, edition.front_id, edition.back_id),
        )


def freeze_edition(db, *, edition_id, front_id, back_id) -> Edition:
    edition = Edition(require_text(edition_id, 'edition_id'),
                      require_text(front_id, 'front_id'),
                      require_text(back_id, 'back_id'))
    revisions = RevisionStore(db)
    front = revisions.get(front_id)
    back = revisions.get(back_id)
    if front is None or back is None:
        raise ValueError('both face revisions must exist')
    if front.side is not FaceSide.FRONT or back.side is not FaceSide.BACK:
        raise ValueError('face revision sides do not match the requested positions')
    store = EditionStore(db)
    existing = store.get(edition_id)
    if existing is not None:
        if existing != edition:
            raise ValueError('edition_id already identifies another face combination')
        return existing
    store.add(edition)
    return edition
