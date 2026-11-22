from dataclasses import dataclass
from datetime import datetime
from app.clock import interval, stamp
from app.errors import InputError
from app.source import identifier


@dataclass(frozen=True)
class Closure:
    line: int
    rink: str
    start: datetime
    end: datetime
    reason: str
    reported: datetime
    reporter: str

    @classmethod
    def read(cls, line, row):
        start, end = interval(row)
        return cls(line, identifier(row, 'rink'), start, end, identifier(row, 'reason'),
                   stamp(row.get('reported')), identifier(row, 'by'))

    def export(self):
        return {'line': self.line, 'rink': self.rink, 'start': self.start.isoformat(),
                'end': self.end.isoformat(), 'reason': self.reason,
                'reported': self.reported.isoformat(), 'by': self.reporter}


@dataclass(frozen=True)
class Migration:
    line: int
    booking: str
    rink: str
    start: datetime | None
    end: datetime | None
    todo: str

    @classmethod
    def read(cls, line, row):
        booking = identifier(row, 'booking')
        has_todo = 'todo' in row
        has_slot = any(field in row for field in ('rink', 'start', 'end'))
        if has_todo == has_slot:
            raise InputError('BAD_ROW')
        if has_todo:
            return cls(line, booking, '', None, None, identifier(row, 'todo'))
        start, end = interval(row)
        return cls(line, booking, identifier(row, 'rink'), start, end, '')

    @property
    def is_move(self):
        return self.start is not None

    def export(self):
        return {'line': self.line, 'booking': self.booking, 'rink': self.rink,
                'start': self.start.isoformat() if self.start else '',
                'end': self.end.isoformat() if self.end else '', 'todo': self.todo}
