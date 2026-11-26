from dataclasses import dataclass

from release.orders import PrintOrder
from release.qualification import WitnessPair, find_register_pair
from setup.proof_sheet import ProofStore


@dataclass(frozen=True)
class StartEligibility:
    status: str
    pair: WitnessPair | None = None


def recheck_order(db, order: PrintOrder) -> StartEligibility:
    proof = ProofStore(db).get(order.proof_id)
    if proof is None:
        raise RuntimeError('print order has no frozen proof sheet')
    pair = find_register_pair(db, proof, order.register_id)
    if pair is None:
        return StartEligibility('recheck_required')
    return StartEligibility('released', pair)


def unstarted_order_status(db, order: PrintOrder) -> str:
    return recheck_order(db, order).status
