import json
import sqlite3

from artwork.face import FaceRevision, FaceSide


class RevisionStore:
    schema = '''CREATE TABLE IF NOT EXISTS face_revisions (
        face_id TEXT PRIMARY KEY NOT NULL,
        side TEXT NOT NULL CHECK (side IN ('front', 'back')),
        bounds TEXT NOT NULL
    )'''

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def add(self, revision: FaceRevision) -> FaceRevision:
        existing = self.get(revision.face_id)
        if existing is not None:
            if existing != revision:
                raise ValueError('face_id already identifies a different revision')
            return existing
        self.db.execute(
            'INSERT INTO face_revisions (face_id, side, bounds) VALUES (?, ?, ?)',
            (revision.face_id, revision.side.value,
             json.dumps([revision.left_mm, revision.right_mm])),
        )
        return revision

    def get(self, face_id: str) -> FaceRevision | None:
        row = self.db.execute(
            'SELECT side, bounds FROM face_revisions WHERE face_id = ?', (face_id,),
        ).fetchone()
        if row is None:
            return None
        return FaceRevision(face_id, FaceSide(row[0]), *json.loads(row[1]))
