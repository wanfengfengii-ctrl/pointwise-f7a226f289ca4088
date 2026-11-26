from dataclasses import dataclass

from printing.completion import Completion, CompletionStore
from printing.press_run import turn_records_for_order
from printing.receipts import ReceiptStore, StartReceipt
from release.orders import OrderStore, PrintOrder
from release.recheck import unstarted_order_status


@dataclass(frozen=True)
class HandoverResult:
    status: str
    order: PrintOrder | None = None
    receipt: StartReceipt | None = None
    completion: Completion | None = None
    press_turns: list[dict] | None = None


def read_handover(db, order_id: str) -> HandoverResult:
    order = OrderStore(db).get(order_id)
    if order is None:
        return HandoverResult('not_found')
    if not order.started:
        return HandoverResult(unstarted_order_status(db, order), order)
    receipt = ReceiptStore(db).get_by_order(order_id)
    if receipt is None:
        raise RuntimeError('started order has no stored receipt')
    completion = CompletionStore(db).get(receipt.start_id)
    status = 'completed' if completion is not None else 'started'
    if receipt.target_count is None:
        return HandoverResult(status, order, receipt, completion)
    return HandoverResult(status, order, receipt, completion,
                          turn_records_for_order(db, receipt.start_id))
