from dataclasses import dataclass

from release.orders import OrderStore, PrintOrder, create_order
from release.qualification import eligible_registers
from release.requests import submit_request
from setup.proof_sheet import ProofStore


@dataclass(frozen=True)
class ReleaseResult:
    status: str
    request_id: str
    order: PrintOrder | None = None


def issue_order(db, *, request_id, edition_id, proof_id) -> ReleaseResult:
    request = submit_request(db, request_id=request_id, edition_id=edition_id, proof_id=proof_id)
    existing = OrderStore(db).get_for_request(request_id)
    if existing is not None:
        return ReleaseResult('released', request_id, existing)
    proof = ProofStore(db).get(request.proof_id)
    if proof is None:
        raise RuntimeError('release request has no frozen proof sheet')
    pair = next(eligible_registers(db, proof), None)
    if pair is None:
        return ReleaseResult('pending', request_id)
    return ReleaseResult('released', request_id, create_order(db, request, pair.register_id))
