from dataclasses import dataclass
import sqlite3

from artwork.edition import EditionStore
from artwork.face import require_text
from setup.proof_sheet import ProofStore


@dataclass(frozen=True)
class ReleaseRequest:
    request_id: str
    edition_id: str
    proof_id: str


class RequestStore:
    schema = '''CREATE TABLE IF NOT EXISTS release_requests (
        request_id TEXT PRIMARY KEY NOT NULL,
        edition_id TEXT NOT NULL REFERENCES editions(edition_id),
        proof_id TEXT NOT NULL REFERENCES proof_sheets(proof_id)
    )'''

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, request_id: str) -> ReleaseRequest | None:
        row = self.db.execute(
            'SELECT edition_id, proof_id FROM release_requests WHERE request_id = ?',
            (request_id,),
        ).fetchone()
        return ReleaseRequest(request_id, *row) if row is not None else None

    def add(self, request: ReleaseRequest) -> None:
        self.db.execute('INSERT INTO release_requests VALUES (?, ?, ?)',
                        (request.request_id, request.edition_id, request.proof_id))


def submit_request(db, *, request_id, edition_id, proof_id) -> ReleaseRequest:
    request = ReleaseRequest(require_text(request_id, 'request_id'),
                             require_text(edition_id, 'edition_id'),
                             require_text(proof_id, 'proof_id'))
    if EditionStore(db).get(edition_id) is None:
        raise ValueError('unknown edition_id')
    proof = ProofStore(db).get(proof_id)
    if proof is None or proof.edition_id != edition_id:
        raise ValueError('proof sheet must belong to the requested edition')
    store = RequestStore(db)
    existing = store.get(request_id)
    if existing is not None:
        if existing != request:
            raise ValueError('request_id already identifies a different release request')
        return existing
    store.add(request)
    return request
