"""Exercise the raw device and prepare the existing HTTP print orders for the bench."""
from dataclasses import asdict
from functools import partial
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from printing.press_device import Reading, open_press


def prepare_orders(post):
    post('/freeze', edition_id='press-exercise', front_id='L2', back_id='R2')
    proof = post('/proof', edition_id='press-exercise', paper_id='P600', table_id='AB')
    for face, left, right in (('L2', 15, 30), ('R2', 25, 25)):
        post('/trial', proof_id=proof['proof_id'], trial_id='press-trial-' + face,
             face_id=face, register_id='A', left_mm=left, right_mm=right)
    orders = {}
    for job in ('A', 'B'):
        result = post('/release', request_id='press-' + job, edition_id='press-exercise',
                      proof_id=proof['proof_id'])
        check(result['status'], 'released')
        check(result['order']['register_id'], 'A')
        orders[job] = result['order']['order_id']
    return orders


def check(actual, expected):
    if actual != expected:
        raise AssertionError(f'expected {expected!r}, got {actual!r}')


def expect_timeout(action, *args):
    try:
        action(*args)
    except TimeoutError:
        return
    raise AssertionError('expected a lost device reply')


def check_drain(open_device):
    with open_device() as press:
        check(press.read(), Reading(100, 1, 0))
        press.interrupt_next_feed(after=2)
        expect_timeout(press.submit, 1, 1, 3)
        check(press.read(), Reading(102, 1, 0))
        check(press.submit(1, 1, 3), 'duplicate')
        check(press.submit(1, 2, 2), 'busy')
    with open_device() as press:
        check(press.read(), Reading(102, 1, 0))
        check(press.resume(1, 1), True)
        drained = press.read()
        check(drained, Reading(103, 1, 1))
        check(press.submit(1, 1, 3), 'duplicate')
        check(press.submit(1, 2, 2), 'accepted')
        next_feed = press.read()
        check(next_feed, Reading(105, 1, 2))
    return {'drained': asdict(drained), 'next_feed': asdict(next_feed)}


def check_cutover(open_device):
    with open_device() as press:
        press.interrupt_next_feed(after=2)
        expect_timeout(press.submit, 1, 1, 3)
        check(press.read(), Reading(102, 1, 0))
        press.lose_next_advance()
        expect_timeout(press.advance, 1)
    with open_device() as press:
        cut = press.read()
        check(cut, Reading(102, 2, 0))
        check(press.advance(1), 'stale')
        check(press.submit(1, 1, 3), 'stale')
        check(press.resume(1, 1), False)
        check(press.read(), cut)
        press.interrupt_next_feed()
        expect_timeout(press.submit, 2, 1, 2)
        check(press.read(), cut)
        check(press.submit(2, 1, 2), 'accepted')
        next_feed = press.read()
        check(next_feed, Reading(104, 2, 1))
    return {'cut': asdict(cut), 'next_feed': asdict(next_feed)}


def main():
    with TemporaryDirectory(prefix='songqiao-press-') as directory:
        root = Path(directory)
        result = {'drain': check_drain(partial(open_press, root / 'drain.db')),
                  'cutover': check_cutover(partial(open_press, root / 'cutover.db'))}
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
