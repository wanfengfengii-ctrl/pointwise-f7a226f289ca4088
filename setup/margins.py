from dataclasses import dataclass

from setup.geometry import PlacedInterval
from setup.paper import PaperSpec


@dataclass(frozen=True)
class EdgeLimits:
    left_mm: int
    right_mm: int


@dataclass(frozen=True)
class EdgeMargins:
    left_mm: int
    right_mm: int


def required_margins(paper: PaperSpec) -> EdgeLimits:
    return EdgeLimits(max(paper.print_left_mm, paper.min_left_mm),
                      max(paper.width_mm - paper.print_right_mm, paper.min_right_mm))


def measure_placement(paper: PaperSpec, placement: PlacedInterval) -> EdgeMargins:
    return EdgeMargins(placement.left_mm, paper.width_mm - placement.right_mm)


def classify_margins(margins: EdgeMargins, limits: EdgeLimits) -> tuple[str, ...]:
    reasons = []
    if margins.left_mm < limits.left_mm:
        reasons.append('left_below_limit')
    if margins.right_mm < limits.right_mm:
        reasons.append('right_below_limit')
    return tuple(reasons)
