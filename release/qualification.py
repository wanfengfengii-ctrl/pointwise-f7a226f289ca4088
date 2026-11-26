from collections.abc import Iterator
from dataclasses import dataclass

from setup.proof_sheet import ProofSheet
from trials.conditions import resolve_trial_condition
from trials.evidence import TrialWitness, select_witness


@dataclass(frozen=True)
class WitnessPair:
    register_id: str
    front: TrialWitness
    back: TrialWitness


def find_register_pair(db, proof: ProofSheet, register_id: str) -> WitnessPair | None:
    if register_id not in proof.common_registers:
        return None
    front = select_witness(db, resolve_trial_condition(proof, proof.front_id, register_id))
    if front is None:
        return None
    back = select_witness(db, resolve_trial_condition(proof, proof.back_id, register_id))
    if back is None:
        return None
    return WitnessPair(register_id, front, back)


def eligible_registers(db, proof: ProofSheet) -> Iterator[WitnessPair]:
    for register_id in proof.common_registers:
        pair = find_register_pair(db, proof, register_id)
        if pair is not None:
            yield pair
