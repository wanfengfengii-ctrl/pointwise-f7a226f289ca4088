from dataclasses import dataclass

from setup.proof_sheet import ProofSheet, get_face_setting


@dataclass(frozen=True)
class TrialCondition:
    face_id: str
    paper_id: str
    table_id: str
    register_id: str


def resolve_trial_condition(proof: ProofSheet, face_id: str, register_id: str) -> TrialCondition:
    setting = get_face_setting(proof, face_id, register_id)
    if setting is None:
        raise ValueError('face revision or actual register is outside the proof sheet')
    if not setting.can_trial:
        raise ValueError('proof sheet does not permit trial on this face at this register')
    return TrialCondition(face_id, proof.paper_id, proof.table_id, register_id)
