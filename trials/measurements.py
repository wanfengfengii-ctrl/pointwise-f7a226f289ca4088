from dataclasses import dataclass

from setup.margins import EdgeLimits, EdgeMargins, classify_margins


@dataclass(frozen=True)
class MeasurementResult:
    measured: EdgeMargins
    passed: bool
    reasons: tuple[str, ...]


def evaluate_measurements(left_mm: int, right_mm: int, limits: EdgeLimits) -> MeasurementResult:
    if type(left_mm) is not int or type(right_mm) is not int:
        raise ValueError('both measured margins must be integer millimetres')
    measured = EdgeMargins(left_mm, right_mm)
    reasons = classify_margins(measured, limits)
    return MeasurementResult(measured, not reasons, reasons)
