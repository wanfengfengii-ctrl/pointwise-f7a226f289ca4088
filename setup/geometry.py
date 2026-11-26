from dataclasses import dataclass

from artwork.face import FaceRevision, FaceSide
from setup.paper import PaperSpec
from setup.registers import RegisterStep


@dataclass(frozen=True)
class PlacedInterval:
    left_mm: int
    right_mm: int


def place_face(face: FaceRevision, paper: PaperSpec, step: RegisterStep) -> PlacedInterval:
    if face.side is FaceSide.FRONT:
        return PlacedInterval(face.left_mm + step.front_offset_mm,
                              face.right_mm + step.front_offset_mm)
    shifted_left = face.left_mm + step.back_offset_mm
    shifted_right = face.right_mm + step.back_offset_mm
    return PlacedInterval(paper.width_mm - shifted_right, paper.width_mm - shifted_left)
