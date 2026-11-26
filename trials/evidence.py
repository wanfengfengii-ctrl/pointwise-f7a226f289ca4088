from collections.abc import Iterator
from dataclasses import dataclass

from trials.conditions import TrialCondition
from trials.disposition import VoidStore
from trials.record import TrialStore


@dataclass(frozen=True)
class TrialWitness:
    trial_id: str
    condition: TrialCondition


def eligible_witnesses(db, condition: TrialCondition) -> Iterator[TrialWitness]:
    dispositions = VoidStore(db)
    for trial in TrialStore(db).for_condition(condition):
        if trial.result.passed and not dispositions.is_voided(trial.trial_id):
            yield TrialWitness(trial.trial_id, trial.condition)


def select_witness(db, condition: TrialCondition) -> TrialWitness | None:
    return next(eligible_witnesses(db, condition), None)
