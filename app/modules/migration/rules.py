from collections import defaultdict
from app.clock import minutes
from app.reasons import evidence

BLOCKING = {'BAD_ROW', 'BAD_TIME', 'BAD_INTERVAL', 'UNCOVERED', 'MISMATCH',
            'MOVE_OVERLAP', 'ORPHAN_MIGRATION', 'TODO_CONFLICT'}


def overlaps(a_start, a_end, b_start, b_end):
    return max(a_start, b_start) < min(a_end, b_end)


def affected_spans(event, closures):
    hits = sorted((c for c in closures
                   if c.rink == event.rink and overlaps(event.start, event.end, c.start, c.end)),
                  key=lambda c: (c.start, c.line))
    spans, basis = [], []
    for closure in hits:
        start, end = max(event.start, closure.start), min(event.end, closure.end)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
        basis.append(closure)
    return spans, basis


def plan(active, closures, migrations):
    issues = []
    moves_by_booking = defaultdict(list)
    todo_by_booking = {}
    for item in migrations:
        if item.is_move:
            moves_by_booking[item.booking].append(item)
        elif item.booking in todo_by_booking:
            issues.append(evidence('TODO_CONFLICT', item.line, item.booking,
                                   lines=[todo_by_booking[item.booking].line, item.line]))
        else:
            todo_by_booking[item.booking] = item
    placed, rows = [], []
    for event in sorted(active, key=lambda e: (e.start, e.rink, e.key)):
        spans, basis = affected_spans(event, closures)
        if not spans:
            continue
        affected = sum(minutes(start, end) for start, end in spans)
        moves = sorted(moves_by_booking.pop(event.key, []), key=lambda m: (m.start, m.line))
        todo = todo_by_booking.pop(event.key, None)
        flagged, moved = set(), 0
        for move in moves:
            moved += minutes(move.start, move.end)
            shut = [c.line for c in closures
                    if c.rink == move.rink and overlaps(move.start, move.end, c.start, c.end)]
            peers = [e.line for e in active
                     if e.rink == move.rink and overlaps(move.start, move.end, e.start, e.end)]
            clash = [p.line for p in placed
                     if p.rink == move.rink and overlaps(move.start, move.end, p.start, p.end)]
            if shut:
                flagged.add('MOVE_OVERLAP')
                issues.append(evidence('MOVE_OVERLAP', move.line, event.key, lines=shut))
            if peers:
                flagged.add('MOVE_OVERLAP')
                issues.append(evidence('MOVE_OVERLAP', move.line, event.key, peers=peers))
            if clash:
                flagged.add('MOVE_OVERLAP')
                issues.append(evidence('MOVE_OVERLAP', move.line, event.key, lines=clash))
            placed.append(move)
        pending = affected - moved
        if moved > affected:
            flagged.add('MISMATCH')
            issues.append(evidence('MISMATCH', moves[-1].line, event.key, minutes=affected, arranged=moved))
        elif todo is not None and moved == affected:
            flagged.add('MISMATCH')
            issues.append(evidence('MISMATCH', todo.line, event.key, minutes=affected, arranged=moved))
        if pending > 0 and todo is None:
            flagged.add('UNCOVERED')
            issues.append(evidence('UNCOVERED', event.line, event.key, minutes=pending))
        slot = [f"→ {m.rink} {m.start:%m-%d %H:%M}–{m.end:%H:%M}" for m in moves]
        if todo is not None:
            slot.append(f"待办：{todo.todo}")
        rows.append({'line': event.line, 'key': event.key, 'owner': event.owner, 'rink': event.rink,
                     'start': event.start.isoformat(), 'end': event.end.isoformat(), 'affected': affected,
                     'basis': '；'.join(f"{c.reason} · {c.reporter} {c.reported:%H:%M} 上报" for c in basis),
                     'basis_lines': [c.line for c in basis],
                     'slot': ' ＋ '.join(slot),
                     'moves': [{'line': m.line, 'rink': m.rink, 'start': m.start.isoformat(),
                                'end': m.end.isoformat()} for m in moves],
                     'todo': todo.todo if todo else '',
                     'moved': moved, 'pending': max(pending, 0),
                     'status': '未落实' if flagged else ('待办' if pending > 0 else '已落实')})
    for key, leftovers in moves_by_booking.items():
        issues.extend(evidence('ORPHAN_MIGRATION', move.line, key) for move in leftovers)
    issues.extend(evidence('ORPHAN_MIGRATION', todo.line, key) for key, todo in todo_by_booking.items())
    return rows, issues
