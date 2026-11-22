from app.errors import InputError
from app.reasons import evidence
from . import rules
from .records import Closure, Migration


def load(closure_rows, migration_rows):
    closures, migrations, issues, seen = [], [], [], set()
    for line, row in enumerate(closure_rows, 1):
        try:
            closure = Closure.read(line, row) if isinstance(row, dict) else None
            if closure is None:
                raise InputError('BAD_ROW')
        except InputError as exc:
            issues.append(evidence(exc.code, line, raw=row))
            continue
        key = (closure.rink, closure.start, closure.end, closure.reason,
               closure.reported, closure.reporter)
        if key in seen:
            issues.append(evidence('DUP_CLOSURE', line, closure.rink, raw=row))
            continue
        seen.add(key)
        closures.append(closure)
    seen = set()
    for line, row in enumerate(migration_rows, 1):
        try:
            migration = Migration.read(line, row) if isinstance(row, dict) else None
            if migration is None:
                raise InputError('BAD_ROW')
        except InputError as exc:
            issues.append(evidence(exc.code, line, raw=row))
            continue
        key = (migration.booking, migration.rink, migration.start, migration.end, migration.todo)
        if key in seen:
            issues.append(evidence('DUP_MIGRATION', line, migration.booking, raw=row))
            continue
        seen.add(key)
        migrations.append(migration)
    return closures, migrations, issues


def plan(active, closures, migrations, shift_balanced, parse_issues):
    rows, issues = rules.plan(active, closures, migrations)
    issues = parse_issues + issues
    sealed = shift_balanced and not any(issue['code'] in rules.BLOCKING for issue in issues)
    return {'rows': rows, 'closures': [c.export() for c in closures], 'issues': issues,
            'sealed': sealed, 'shift_balanced': shift_balanced,
            'metrics': {'封场段': len(closures), '受影响预订': len(rows),
                        '已迁移（分）': sum(row['moved'] for row in rows),
                        '待办（分）': sum(row['pending'] for row in rows if row['status'] == '待办'),
                        '未落实': sum(1 for row in rows if row['status'] == '未落实')}}
