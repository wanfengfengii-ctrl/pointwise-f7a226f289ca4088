from dataclasses import dataclass
from enum import StrEnum


class FaceSide(StrEnum):
    FRONT = 'front'
    BACK = 'back'


def require_text(value, field):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(f'{field} must be a nonempty string without NUL')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError(f'{field} must contain valid Unicode') from exc
    return value


def validate_face_bounds(left_mm: int, right_mm: int) -> None:
    if type(left_mm) is not int or type(right_mm) is not int:
        raise ValueError('face bounds must be integers in millimetres')
    if not 0 <= left_mm < right_mm:
        raise ValueError('face bounds must satisfy 0 <= left_mm < right_mm')


@dataclass(frozen=True)
class FaceRevision:
    face_id: str
    side: FaceSide
    left_mm: int
    right_mm: int

    def __post_init__(self):
        require_text(self.face_id, 'face_id')
        if not isinstance(self.side, FaceSide):
            raise ValueError('side must be front or back')
        validate_face_bounds(self.left_mm, self.right_mm)
