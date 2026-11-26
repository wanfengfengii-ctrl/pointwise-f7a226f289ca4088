"""Persistent counter and command interface for the bench press simulator."""
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class Reading:
    counter: int
    generation: int
    drained_through: int


class Press:
    def __init__(self, db):
        self.db = db
        db.executescript('''
            CREATE TABLE IF NOT EXISTS head (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                counter TEXT NOT NULL,
                generation INTEGER NOT NULL,
                drained_through INTEGER NOT NULL,
                next_feed TEXT,
                lose_advance INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO head VALUES (1, '100', 1, 0, NULL, 0);
            CREATE TABLE IF NOT EXISTS feed_commands (
                generation INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                requested TEXT NOT NULL,
                remaining TEXT NOT NULL,
                PRIMARY KEY (generation, slot)
            );
        ''')

    @contextmanager
    def _write(self):
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            yield

    def read(self):
        counter, generation, drained = self.db.execute(
            'SELECT counter, generation, drained_through FROM head WHERE singleton = 1'
        ).fetchone()
        return Reading(int(counter), generation, drained)

    def submit(self, generation, slot, count):
        if any(type(value) is not int or value < 1 for value in (generation, slot, count)):
            raise ValueError('generation, slot and count must be positive integers')
        with self._write():
            current = self.read()
            if generation != current.generation:
                return 'stale'
            row = self.db.execute(
                'SELECT requested FROM feed_commands WHERE generation = ? AND slot = ?',
                (generation, slot),
            ).fetchone()
            if row is not None:
                if int(row[0]) != count:
                    raise ValueError('device command slot already has a different count')
                return 'duplicate'
            if slot != current.drained_through + 1:
                return 'busy'
            behavior = self.db.execute('SELECT next_feed FROM head').fetchone()[0]
            self.db.execute('UPDATE head SET next_feed = NULL')
            if behavior != 'drop':
                printed = count if behavior is None else min(count, int(behavior))
                self.db.execute('INSERT INTO feed_commands VALUES (?, ?, ?, ?)',
                                (generation, slot, str(count), str(count - printed)))
                drained = slot if printed == count else current.drained_through
                self.db.execute('UPDATE head SET counter = ?, drained_through = ?',
                                (str(current.counter + printed), drained))
        if behavior is not None:
            raise TimeoutError('device feed reply lost')
        return 'accepted'

    def advance(self, expected_generation):
        if type(expected_generation) is not int or expected_generation < 1:
            raise ValueError('expected_generation must be a positive integer')
        with self._write():
            current = self.read()
            if current.generation != expected_generation:
                return 'stale'
            lost = self.db.execute('SELECT lose_advance FROM head').fetchone()[0]
            self.db.execute('UPDATE head SET generation = ?, drained_through = 0, lose_advance = 0',
                            (expected_generation + 1,))
        if lost:
            raise TimeoutError('device advance reply lost')
        return 'advanced'

    # The bench operator controls these in exercises. The service uses read/submit/advance.
    def interrupt_next_feed(self, after=None):
        if after is not None and (type(after) is not int or after < 0):
            raise ValueError('after must be a nonnegative integer or None')
        with self._write():
            self.db.execute('UPDATE head SET next_feed = ?', ('drop' if after is None else str(after),))

    def lose_next_advance(self):
        with self._write():
            self.db.execute('UPDATE head SET lose_advance = 1')

    def resume(self, generation, slot):
        with self._write():
            current = self.read()
            if generation != current.generation or slot != current.drained_through + 1:
                return False
            row = self.db.execute(
                'SELECT remaining FROM feed_commands WHERE generation = ? AND slot = ?',
                (generation, slot),
            ).fetchone()
            if row is None:
                return False
            self.db.execute("UPDATE feed_commands SET remaining = '0' WHERE generation = ? AND slot = ?",
                            (generation, slot))
            self.db.execute('UPDATE head SET counter = ?, drained_through = ?',
                            (str(current.counter + int(row[0])), slot))
            return True


def press_path(workbench_database):
    path = Path(workbench_database)
    return path.with_name(path.name + '.press.sqlite3')


@contextmanager
def open_press(workbench_database):
    with closing(sqlite3.connect(press_path(workbench_database), timeout=5,
                                 isolation_level=None)) as db:
        yield Press(db)
