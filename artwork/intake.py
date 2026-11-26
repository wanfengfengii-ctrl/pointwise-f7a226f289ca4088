from artwork.face import FaceRevision, FaceSide
from artwork.revisions import RevisionStore


def register_face(db, *, face_id, side, left_mm, right_mm) -> FaceRevision:
    try:
        orientation = FaceSide(side)
    except (ValueError, TypeError) as exc:
        raise ValueError('side must be front or back') from exc
    revision = FaceRevision(face_id, orientation, left_mm, right_mm)
    return RevisionStore(db).add(revision)
