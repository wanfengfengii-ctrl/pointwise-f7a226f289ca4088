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


_UNSET = object()


def require_target(target_count):
    if type(target_count) is not int or target_count < 1:
        raise ValueError('target_count must be a positive integer')
    return target_count


def confirm_start(db, *, order_id, confirmation_id, target_count=_UNSET) -> StartResult:
    require_text(order_id, 'order_id')
    require_text(confirmation_id, 'confirmation_id')
    target_provided = target_count is not _UNSET
    if target_provided:
        target_count = require_target(target_count)
    else:
        target_count = None
    order = OrderStore(db).get(order_id)
    if order is None:
        return StartResult('not_found', order_id)
    receipts = ReceiptStore(db)
    existing = receipts.get_by_order(order_id)
    if existing is not None:
        if existing.confirmation_id != confirmation_id:
            raise ValueError('order has already started under a different confirmation')
        existing_is_segmented = existing.target_count is not None
        if target_provided != existing_is_segmented or (
                target_provided and existing.target_count != target_count):
            raise ValueError('repeated confirmation must keep the original mode and target_count')
        return StartResult('started', order_id, existing)
    if order.started:
        raise RuntimeError('started order has no stored receipt')
    if receipts.get_by_confirmation(confirmation_id) is not None:
        raise ValueError('confirmation_id already belongs to another order')

    eligibility = recheck_order(db, order)
    if eligibility.pair is None:
        return StartResult(eligibility.status, order_id)
    receipt = receipts.add(order, confirmation_id, eligibility.pair, target_count)
    mark_order_started(db, order_id)
    return StartResult('started', order_id, receipt)
