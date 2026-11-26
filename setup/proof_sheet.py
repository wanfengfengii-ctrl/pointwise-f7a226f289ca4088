from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import sqlite3

from artwork.edition import EditionStore
from artwork.face import require_text
from artwork.revisions import RevisionStore
from setup.geometry import place_face
from setup.margins import EdgeLimits, EdgeMargins, classify_margins, measure_placement, required_margins
from setup.paper import PaperStore
from setup.registers import RegisterStore


@dataclass(frozen=True)
class FaceProof:
    face_id: str
    margins: EdgeMargins
    can_trial: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ProofSheet:
    proof_id: str
    edition_id: str
    paper_id: str
    table_id: str
    front_id: str
    back_id: str
    limits: EdgeLimits
    settings: dict[str, dict[str, FaceProof]]
    common_registers: tuple[str, ...]
    reasons: tuple[str, ...]


class ProofStore:
    schema = '''CREATE TABLE IF NOT EXISTS proof_sheets (
        proof_id TEXT PRIMARY KEY NOT NULL,
        edition_id TEXT NOT NULL REFERENCES editions(edition_id),
        paper_id TEXT NOT NULL REFERENCES papers(paper_id),
        table_id TEXT NOT NULL REFERENCES register_tables(table_id),
        snapshot TEXT NOT NULL,
        UNIQUE (edition_id, paper_id, table_id)
    )'''

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, proof_id: str) -> ProofSheet | None:
        row = self.db.execute(
            'SELECT snapshot FROM proof_sheets WHERE proof_id = ?', (proof_id,),
        ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        data['limits'] = EdgeLimits(**data['limits'])
        data['common_registers'] = tuple(data['common_registers'])
        data['reasons'] = tuple(data['reasons'])
        for settings in data['settings'].values():
            for side, entry in settings.items():
                settings[side] = FaceProof(entry['face_id'], EdgeMargins(**entry['margins']),
                                           entry['can_trial'], tuple(entry['reasons']))
        return ProofSheet(**data)

    def add(self, proof: ProofSheet) -> None:
        self.db.execute(
            'INSERT INTO proof_sheets VALUES (?, ?, ?, ?, ?)',
            (proof.proof_id, proof.edition_id, proof.paper_id, proof.table_id,
             json.dumps(asdict(proof))),
        )


def build_proof_sheet(db, *, edition_id, paper_id, table_id) -> ProofSheet:
    identities = [require_text(edition_id, 'edition_id'), require_text(paper_id, 'paper_id'),
                  require_text(table_id, 'table_id')]
    edition = EditionStore(db).get(edition_id)
    paper = PaperStore(db).get(paper_id)
    table = RegisterStore(db).get(table_id)
    if edition is None or paper is None or table is None:
        raise ValueError('proof requires a known edition, paper and register table')
    proof_id = 'P-' + sha256(json.dumps(identities).encode('ascii')).hexdigest()
    store = ProofStore(db)
    existing = store.get(proof_id)
    if existing is not None:
        return existing

    revisions = RevisionStore(db)
    faces = (revisions.get(edition.front_id), revisions.get(edition.back_id))
    if any(face is None for face in faces):
        raise RuntimeError('frozen edition has a missing face revision')
    limits = required_margins(paper)
    settings = {}
    common = []
    for step in table.steps:
        sides = {}
        for face in faces:
            margins = measure_placement(paper, place_face(face, paper, step))
            reasons = classify_margins(margins, limits)
            sides[face.side.value] = FaceProof(face.face_id, margins, not reasons, reasons)
        settings[step.register_id] = sides
        if sides['front'].can_trial and sides['back'].can_trial:
            common.append(step.register_id)

    proof = ProofSheet(proof_id, edition_id, paper_id, table_id, edition.front_id,
                       edition.back_id, limits, settings, tuple(common),
                       () if common else ('no_common_register',))
    store.add(proof)
    return proof


def get_face_setting(proof: ProofSheet, face_id: str, register_id: str) -> FaceProof | None:
    sides = proof.settings.get(register_id)
    if sides is None:
        return None
    if face_id == proof.front_id:
        return sides['front']
    if face_id == proof.back_id:
        return sides['back']
    return None
