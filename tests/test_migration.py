import json
from io import BytesIO
from app import clock, source
from app.modules.bookings import service as bookings
from app.modules.changes import service as shift
from app.modules.migration import service
from app.pipeline import process
from app.source import sample
from app.store import history


def night_data():
    return json.loads(sample('night'))


def run_with(data):
    return process(json.dumps(data, ensure_ascii=False).encode())['migration']


def post_source(client, data):
    payload = json.dumps(data, ensure_ascii=False).encode()
    return client.post('/api/runs', data={'source': (BytesIO(payload), 'case.json')})


def test_fault_night_ticket_sealed_with_full_disposition(ledger):
    migration = ledger['migration']
    assert migration['sealed'] and migration['shift_balanced']
    assert migration['metrics'] == {'封场段': 1, '受影响预订': 4, '已迁移（分）': 50,
                                    '待办（分）': 40, '未落实': 0}
    rows = {row['key']: row for row in migration['rows']}
    assert [(rows[k]['affected'], rows[k]['moved'], rows[k]['pending'])
            for k in ('0042', '0043', '0048', '0049')] == [(30, 30, 0), (20, 0, 20),
                                                           (20, 20, 0), (20, 0, 20)]
    assert [rows[k]['status'] for k in ('0042', '0043', '0048', '0049')] == ['已落实', '待办', '已落实', '待办']


def test_page_row_shows_original_basis_and_disposition(ledger):
    rows = {row['key']: row for row in ledger['migration']['rows']}
    moved, pending = rows['0042'], rows['0043']
    assert (moved['owner'], moved['rink'], moved['line']) == ('纸鸢', '北冰', 1)
    assert moved['start'] == '2026-11-20T23:40:00+08:00' and moved['end'] == '2026-11-21T00:20:00+08:00'
    assert moved['basis'] == '制冰机报障 · 维护组 23:35 上报' and moved['basis_lines'] == [1]
    assert moved['slot'] == '→ 南冰 11-21 00:50–01:20'
    assert moved['moves'] == [{'line': 1, 'rink': '南冰', 'start': '2026-11-21T00:50:00+08:00',
                               'end': '2026-11-21T01:20:00+08:00'}]
    assert pending['slot'].startswith('待办：') and pending['todo']
    closure, = ledger['migration']['closures']
    assert closure['reason'] == '制冰机报障' and closure['by'] == '维护组'
    assert closure['reported'] == '2026-11-20T23:35:00+08:00'


def test_rerun_same_batch_adds_no_migration_items(client):
    first = client.post('/api/runs', json={'sample': 'night'}).json
    second = client.post('/api/runs', json={'sample': 'night'}).json
    assert second['reused'] and second['id'] == first['id']
    assert second['views']['migration']['rows'] == first['views']['migration']['rows']
    again = client.post(f"/api/runs/{first['id']}/rerun").json
    assert again['views']['migration']['rows'] == first['views']['migration']['rows']
    assert len(again['views']['migration']['rows']) == 4
    assert len(history(client.application.config['DB_PATH'])) == 1


def test_retransmitted_migration_row_stays_single_item():
    data = night_data()
    data['migrations'].append(dict(data['migrations'][0]))
    migration = run_with(data)
    row = next(row for row in migration['rows'] if row['key'] == '0042')
    assert row['moved'] == 30 and len(row['moves']) == 1
    assert [issue['line'] for issue in migration['issues'] if issue['code'] == 'DUP_MIGRATION'] == [5]
    assert migration['sealed']


def test_export_loses_neither_booking_nor_closure_basis(client):
    created = client.post('/api/runs', json={'sample': 'night'}).json
    export = json.loads(client.get(f"/api/runs/{created['id']}/export").data)
    migration = export['views']['migration']
    assert migration['closures'][0]['reason'] == '制冰机报障'
    row = next(row for row in migration['rows'] if row['key'] == '0042')
    assert (row['start'], row['end'], row['owner']) == ('2026-11-20T23:40:00+08:00',
                                                        '2026-11-21T00:20:00+08:00', '纸鸢')
    kept = export['views']['changes']['rows']
    assert any(r['key'] == '0042' and r['start'] == '2026-11-20T23:40:00+08:00' for r in kept)
    assert '制冰机报障' in export['original_json']


def test_broken_closure_row_kept_as_evidence_and_blocks_seal():
    data = night_data()
    data['closures'].append({'rink': '西冰', 'start': '2026-11-21T02:00:00+08:00',
                             'end': '2026-11-21T03:00:00+08:00', 'reason': '',
                             'reported': '2026-11-21T01:50:00+08:00', 'by': '维护组'})
    migration = run_with(data)
    issue = next(issue for issue in migration['issues'] if issue['code'] == 'BAD_ROW')
    assert issue['raw'] == data['closures'][1] and issue['line'] == 2
    assert not migration['sealed']


def test_uncovered_booking_cannot_become_formal_ticket(client):
    data = night_data()
    data['migrations'] = [m for m in data['migrations'] if m['booking'] != '0049']
    migration = run_with(data)
    issue = next(issue for issue in migration['issues'] if issue['code'] == 'UNCOVERED')
    assert issue['key'] == '0049' and issue['minutes'] == 20
    assert next(row for row in migration['rows'] if row['key'] == '0049')['status'] == '未落实'
    assert not migration['sealed']
    created = post_source(client, data).json
    assert created['views']['migration']['sealed'] is False
    refused = client.get(f"/api/runs/{created['id']}/ticket")
    assert refused.status_code == 422 and refused.json['code'] == 'TICKET_UNSEALED'
    draft = client.get(f"/api/modules/migration/{created['id']}").json
    assert len(draft['rows']) == 4


def test_move_overlapping_existing_booking_cannot_seal():
    data = night_data()
    move = next(m for m in data['migrations'] if m['booking'] == '0042')
    move['start'], move['end'] = '2026-11-21T00:30:00+08:00', '2026-11-21T01:00:00+08:00'
    migration = run_with(data)
    issue = next(issue for issue in migration['issues'] if issue['code'] == 'MOVE_OVERLAP')
    assert issue['key'] == '0042' and issue['peers'] == [7]
    assert not migration['sealed']


def test_move_into_closed_segment_cannot_seal():
    data = night_data()
    move = next(m for m in data['migrations'] if m['booking'] == '0042')
    move['rink'], move['start'], move['end'] = '北冰', '2026-11-21T00:30:00+08:00', '2026-11-21T01:00:00+08:00'
    migration = run_with(data)
    assert any(issue['code'] == 'MOVE_OVERLAP' and issue.get('lines') == [1]
               for issue in migration['issues'])
    assert not migration['sealed']


def test_moves_overlapping_each_other_cannot_seal():
    data = night_data()
    first = next(m for m in data['migrations'] if m['booking'] == '0048')
    first['start'], first['end'] = '2026-11-21T01:10:00+08:00', '2026-11-21T01:30:00+08:00'
    migration = run_with(data)
    assert any(issue['code'] == 'MOVE_OVERLAP' and issue.get('lines') == [1]
               for issue in migration['issues'])
    assert not migration['sealed']


def test_minutes_mismatch_cannot_seal():
    data = night_data()
    move = next(m for m in data['migrations'] if m['booking'] == '0042')
    move['start'], move['end'] = '2026-11-21T00:40:00+08:00', '2026-11-21T01:20:00+08:00'
    migration = run_with(data)
    issue = next(issue for issue in migration['issues'] if issue['code'] == 'MISMATCH')
    assert issue['key'] == '0042' and issue['minutes'] == 30 and issue['arranged'] == 40
    assert not migration['sealed']


def test_orphan_migration_cannot_seal():
    data = night_data()
    data['migrations'].append({'booking': '9999', 'todo': '查无此单'})
    migration = run_with(data)
    issue = next(issue for issue in migration['issues'] if issue['code'] == 'ORPHAN_MIGRATION')
    assert issue['key'] == '9999' and issue['line'] == 5
    assert not migration['sealed']


def test_conflicting_todos_cannot_seal():
    data = night_data()
    data['migrations'].append({'booking': '0043', 'todo': '另一套待办口径'})
    migration = run_with(data)
    issue = next(issue for issue in migration['issues'] if issue['code'] == 'TODO_CONFLICT')
    assert issue['key'] == '0043' and issue['lines'] == [2, 5]
    assert not migration['sealed']


def test_redundant_todo_after_full_move_cannot_seal():
    data = night_data()
    data['migrations'].append({'booking': '0042', 'todo': '多余待办'})
    migration = run_with(data)
    assert any(issue['code'] == 'MISMATCH' and issue['key'] == '0042' for issue in migration['issues'])
    assert not migration['sealed']


def test_partial_move_plus_todo_still_seals():
    data = night_data()
    move = next(m for m in data['migrations'] if m['booking'] == '0042')
    move['end'] = '2026-11-21T01:10:00+08:00'
    data['migrations'].append({'booking': '0042', 'todo': '其余分钟班后改期'})
    migration = run_with(data)
    row = next(row for row in migration['rows'] if row['key'] == '0042')
    assert (row['moved'], row['pending'], row['status']) == (20, 10, '待办')
    assert '＋' in row['slot']
    assert migration['sealed']


def test_unbalanced_shift_cannot_seal_even_with_clean_plan(night):
    events, _ = bookings.load(night['events'])
    active, _ = shift.replay(events, clock.stamp(night['cutoff']))
    closures, migrations, intake = service.load(night['closures'], night['migrations'])
    view = service.plan(active, closures, migrations, False, intake)
    assert view['sealed'] is False and view['shift_balanced'] is False
    assert not view['issues']


def test_ticket_export_matches_shown_result(client):
    created = client.post('/api/runs', json={'sample': 'night'}).json
    run = created['id']
    shown = client.get(f'/api/modules/migration/{run}').json
    response = client.get(f'/api/runs/{run}/ticket')
    assert response.status_code == 200 and 'attachment' in response.headers['Content-Disposition']
    ticket = json.loads(response.data)
    assert ticket['ticket'] == '封场迁移单' and ticket['sealed'] and ticket['run'] == run
    assert ticket['rows'] == shown['rows'] and ticket['closures'] == shown['closures']
    assert ticket['input_sha256'] == created['manifest']['input_sha256']


def test_ticket_endpoint_404s(client):
    missing = client.get('/api/runs/side-not-found/ticket')
    assert missing.status_code == 404 and missing.json['code'] == 'RUN_MISSING'


def test_migration_page_renders_seal_and_basis(client):
    created = client.post('/api/runs', json={'sample': 'night'}).json
    page = client.get(f"/desk/migration?run={created['id']}").data.decode()
    assert '封场迁移单' in page and '制冰机报障' in page
    assert '已封存 · 可交接' in page and '下载迁移单凭证' in page
    clean = client.post('/api/runs', json={'sample': 'clean'}).json
    quiet = client.get(f"/desk/migration?run={clean['id']}").data.decode()
    assert '本班没有封场记录' in quiet
