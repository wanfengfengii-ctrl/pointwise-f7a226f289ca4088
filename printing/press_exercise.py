"""Exercise the raw device and prepare the existing HTTP print orders for the bench."""
from dataclasses import asdict
from functools import partial
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from printing.press_device import Reading, open_press


def prepare_orders(post, prefix='press'):
    edition_id = prefix + '-exercise'
    post('/freeze', edition_id=edition_id, front_id='L2', back_id='R2')
    proof = post('/proof', edition_id=edition_id, paper_id='P600', table_id='AB')
    for face, left, right in (('L2', 15, 30), ('R2', 25, 25)):
        post('/trial', proof_id=proof['proof_id'], trial_id=prefix + '-trial-' + face,
             face_id=face, register_id='A', left_mm=left, right_mm=right)
    orders = {}
    for job in ('A', 'B'):
        result = post('/release', request_id=prefix + '-' + job, edition_id=edition_id,
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


def _step(emit, name, response):
    if emit is not None:
        emit({'step': name, 'response': response})


def _post(post, emit, name, path, *, code=200, **data):
    status, body = post(path, **data)
    _step(emit, name, {'http_status': status, 'body': body})
    check(status, code)
    return body


def _get(get, emit, name, path, identity, *, code=200):
    status, body = get(path, identity)
    _step(emit, name, {'http_status': status, 'body': body})
    check(status, code)
    return body


def run_press_wheel(post, get, open_device, *, mode, emit=None, suffix=''):
    """Drive the A/B/A segmented wheel over real HTTP and the shared press file.

    post/get must return ``(http_status, body)`` tuples. open_device opens the same
    press file the workbench uses. mode selects how the first interrupted feed is
    resolved: ``drain`` lets the stuck third sheet print (100->103); ``cutover``
    truncates it (100->102). suffix isolates ids when wheels share one database.
    """
    if mode not in ('drain', 'cutover'):
        raise ValueError('mode must be drain or cutover')
    prefix = 'press' + suffix
    base_orders = prepare_orders(lambda path, **data: post(path, **data)[1], prefix)
    job_a, job_b = base_orders['A'], base_orders['B']
    starts = {
        job: _post(post, emit, 'start-' + job, '/start', order_id=order_id,
                   confirmation_id='mount-' + job + suffix, target_count=target)['receipt']
        for job, order_id, target in (('A', job_a, 5), ('B', job_b, 2))
    }
    check(starts['A']['target_count'], 5)
    check(starts['B']['target_count'], 2)
    start_a, start_b = starts['A']['start_id'], starts['B']['start_id']

    def tid(name):
        return name + suffix

    a1, b1, a2 = tid('turn-A1'), tid('turn-B1'), tid('turn-A2')

    with open_device() as press:
        press.interrupt_next_feed(after=2)

    # turn-A1: three sheets requested, the third may still be in flight.
    turn_a1 = _post(post, emit, a1 + '-open', '/press-turn', start_id=start_a, turn_id=a1)
    origin = turn_a1['start_counter']
    check(turn_a1, {'status': 'active', 'turn_id': a1, 'start_id': start_a,
                    'start_counter': origin, 'end_counter': None, 'count': None})
    pending = _post(post, emit, a1 + '-feed-pending', '/press-feed', code=202,
                    turn_id=a1, count=3)
    check(pending, {'status': 'pending', 'turn_id': a1, 'count': 3})
    with open_device() as press:
        check(press.read().counter, origin + 2)
    # Same parameters replay the original feed without a second submission;
    # the reply stays lost until the stuck sheet is drained.
    replay = _post(post, emit, a1 + '-feed-replay', '/press-feed', code=202,
                   turn_id=a1, count=3)
    check(replay, pending)
    with open_device() as press:
        check(press.read().counter, origin + 2)
    check(_get(get, emit, a1 + '-query', '/press-turn', a1)['status'], 'active')
    _post(post, emit, b1 + '-blocked', '/press-turn', code=400,
          start_id=start_b, turn_id=b1)
    _post(post, emit, a1 + '-feed-change-rejected', '/press-feed', code=400,
          turn_id=a1, count=4)

    # First handover only reports the unverified feed.
    yielding = _post(post, emit, a1 + '-yielding', '/press-yield', code=202, turn_id=a1)
    check(yielding['status'], 'yielding')
    check(yielding['end_counter'], None)
    # A new first feed is closed; same-parameter replays still read back the original feed.
    check(_post(post, emit, a1 + '-feed-replay-yielding', '/press-feed', code=202,
                turn_id=a1, count=3), pending)
    _post(post, emit, a1 + '-feed-closed', '/press-feed', code=400, turn_id=a1, count=2)

    if mode == 'drain':
        with open_device() as press:
            reading = press.read()
            check(press.resume(reading.generation, reading.drained_through + 1), True)
            check(press.read().counter, origin + 3)
        # The feed is now fully drained, so the retried handover seals immediately.
        resolved = _post(post, emit, a1 + '-yield-drained', '/press-yield', code=200,
                         turn_id=a1)
        check(resolved, {'status': 'yielded', 'turn_id': a1, 'start_id': start_a,
                         'start_counter': origin, 'end_counter': origin + 3, 'count': 3})
    else:
        with open_device() as press:
            press.lose_next_advance()
        # The advance commits before its reply is lost, so the handover stays a todo.
        lost = _post(post, emit, a1 + '-advance-lost', '/press-yield', code=202, turn_id=a1)
        check(lost['end_counter'], origin + 2)
        with open_device() as press:
            reading = press.read()
            old_generation = reading.generation - 1
            check(reading.generation, old_generation + 1)
            check(press.advance(old_generation), 'stale')
            check(press.submit(old_generation, 1, 3), 'stale')
            check(press.resume(old_generation, 1), False)
            check(press.read().counter, origin + 2)
        resolved = _post(post, emit, a1 + '-yield-cut', '/press-yield', turn_id=a1)
        check(resolved, {'status': 'yielded', 'turn_id': a1, 'start_id': start_a,
                         'start_counter': origin, 'end_counter': origin + 2, 'count': 2})
    check(_post(post, emit, a1 + '-yield-replay', '/press-yield', turn_id=a1), resolved)

    # A cannot finish after only its first turn.
    _post(post, emit, 'finish-A-early-rejected', '/finish', code=400,
          start_id=start_a, good_count=2, waste_count=0)

    # B prints its full order while A is paused.
    _post(post, emit, b1 + '-open', '/press-turn', start_id=start_b, turn_id=b1)
    _post(post, emit, b1 + '-feed', '/press-feed', turn_id=b1, count=2)
    turn_b1 = _post(post, emit, b1 + '-yield', '/press-yield', turn_id=b1)
    check(turn_b1['count'], 2)

    # A resumes for the remainder of its target (3 after the cut 2, 2 after the drain 3).
    _post(post, emit, a2 + '-open', '/press-turn', start_id=start_a, turn_id=a2)
    a2_count = 5 - resolved['count']
    _post(post, emit, a2 + '-feed', '/press-feed', turn_id=a2, count=a2_count)
    turn_a2 = _post(post, emit, a2 + '-yield', '/press-yield', turn_id=a2)
    check(turn_a2['count'], a2_count)
    with open_device() as press:
        final_counter = press.read().counter
    # Each order prints its full target: 5 for A across two turns, 2 for B.
    check(final_counter, origin + 7)
    check(turn_b1['start_counter'], resolved['end_counter'])
    check(turn_a2['start_counter'], turn_b1['end_counter'])
    check(resolved['start_counter'] < resolved['end_counter'] <= turn_b1['start_counter'], True)
    check(turn_b1['end_counter'] <= turn_a2['start_counter'] < turn_a2['end_counter'], True)

    # Finish accounting: good + waste must equal the confirmed press count.
    _post(post, emit, 'finish-A-bad-sum-rejected', '/finish', code=400,
          start_id=start_a, good_count=4, waste_count=0)
    _post(post, emit, 'finish-B', '/finish', start_id=start_b, good_count=2, waste_count=0)
    completion_a = _post(post, emit, 'finish-A', '/finish',
                         start_id=start_a, good_count=4, waste_count=1)

    handover_a = _get(get, emit, 'receipt-A', '/receipt', job_a)
    handover_b = _get(get, emit, 'receipt-B', '/receipt', job_b)
    check(handover_a['status'], 'completed')
    check(handover_a['completion'], completion_a)
    check(handover_b['completion'],
          {'start_id': start_b, 'good_count': 2, 'waste_count': 0})
    expected_a = [
        {'status': 'yielded', 'turn_id': a1, 'start_id': start_a,
         'start_counter': origin, 'end_counter': resolved['end_counter'],
         'count': resolved['count']},
        {'status': 'yielded', 'turn_id': a2, 'start_id': start_a,
         'start_counter': turn_a2['start_counter'], 'end_counter': final_counter,
         'count': a2_count},
    ]
    check(handover_a['press_turns'], expected_a)
    check([turn['turn_id'] for turn in handover_b['press_turns']], [b1])
    check(len(handover_b['press_turns']), 1)
    check(handover_b['press_turns'][0], turn_b1)
    with open_device() as press:
        final_counter = press.read().counter
    return {
        'mode': mode,
        'orders': {'A': job_a, 'B': job_b},
        'start_ids': {'A': start_a, 'B': start_b},
        'turns': {a1: resolved, b1: turn_b1, a2: turn_a2},
        'completions': {'A': completion_a, 'B': handover_b['completion']},
        'handovers': {'A': handover_a, 'B': handover_b},
        'final_counter': final_counter,
    }


def main():
    with TemporaryDirectory(prefix='songqiao-press-') as directory:
        root = Path(directory)
        result = {'drain': check_drain(partial(open_press, root / 'drain.db')),
                  'cutover': check_cutover(partial(open_press, root / 'cutover.db'))}
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
