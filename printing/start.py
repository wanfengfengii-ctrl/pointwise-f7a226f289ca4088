from dataclasses import dataclass

from artwork.face import require_text
from printing.receipts import ReceiptStore, StartReceipt
from release.orders import OrderStore, mark_order_started
from release.recheck import recheck_order


@dataclass(frozen=True)
class StartResult:
    status: str
    order_id: str
    receipt: StartReceipt | None = None


def confirm_start(db, *, order_id, confirmation_id) -> StartResult:
    require_text(order_id, 'order_id')
    require_text(confirmation_id, 'confirmation_id')
    order = OrderStore(db).get(order_id)
    if order is None:
        return StartResult('not_found', order_id)
    receipts = ReceiptStore(db)
    existing = receipts.get_by_order(order_id)
    if existing is not None:
        if existing.confirmation_id != confirmation_id:
            raise ValueError('order has already started under a different confirmation')
        return StartResult('started', order_id, existing)
    if order.started:
        raise RuntimeError('started order has no stored receipt')
    if receipts.get_by_confirmation(confirmation_id) is not None:
        raise ValueError('confirmation_id already belongs to another order')

    eligibility = recheck_order(db, order)
    if eligibility.pair is None:
        return StartResult(eligibility.status, order_id)
    receipt = receipts.add(order, confirmation_id, eligibility.pair)
    mark_order_started(db, order_id)
    return StartResult('started', order_id, receipt)
