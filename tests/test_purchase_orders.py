import json

import pytest

from app.config import SAMPLE


def _fx_file(tmp_path, rates):
    path = tmp_path / 'fx.json'
    path.write_text(json.dumps({'base': 'CNY', 'source': 'test', 'as_of': '2026-11-18', 'rates': rates}), encoding='utf-8')
    return str(path)


GOOD_RATES = {
    'USD': {'2026-11-15': '7.0800', '2026-11-16': '7.1000', '2026-11-17': '7.1200', '2026-11-18': '7.1500'},
    'CNY': {'2026-11-15': '1', '2026-11-16': '1', '2026-11-17': '1', '2026-11-18': '1'},
}


def test_fx_endpoint_serves_snapshot(client):
    body = client.get('/api/fx').get_json()
    assert body['base'] == 'CNY' and body['rates']['USD']['2026-11-17'] == '7.1200'


def test_fx_endpoint_reports_bad_source(client, tmp_path, monkeypatch):
    monkeypatch.setenv('FX_SOURCE', str(tmp_path / 'missing.json'))
    response = client.get('/api/fx')
    assert response.status_code == 502 and response.get_json()['code'] == 'FX_LOAD'


def test_failure_keeps_previous_candidates(client, tmp_path, monkeypatch):
    good = _fx_file(tmp_path, GOOD_RATES)
    monkeypatch.setenv('FX_SOURCE', good)
    first = client.post('/api/run', json={}).get_json()
    before = first['stages']['6']['rows']
    assert before and first['stages']['6']['fx_status'] == 'snapshot'

    monkeypatch.setenv('FX_SOURCE', str(tmp_path / 'broken.json'))
    fallback = client.post('/api/run', json={}).get_json()
    stage6 = fallback['stages']['6']
    assert stage6['fx_status'] == 'fallback'
    assert stage6['rows'] == before
    assert any(q['原因码'] == 'FX_FALLBACK' for q in fallback['quarantine'])
    # 已确认成本口径：折算金额沿用旧版，不被重算
    assert stage6['metrics'][1][1] == first['stages']['6']['metrics'][1][1]


def test_failure_without_previous_run_marks_unavailable(client, tmp_path, monkeypatch):
    monkeypatch.setenv('FX_SOURCE', str(tmp_path / 'broken.json'))
    result = client.post('/api/run', json={}).get_json()
    assert result['stages']['6']['fx_status'] == 'unavailable'
    assert all(r['币种'] == 'CNY' for r in result['stages']['6']['rows'])
    assert any(q['原因码'] == 'FX_MISSING' for q in result['quarantine'])


def test_retry_same_batch_creates_no_extra_purchase_orders(client, tmp_path, monkeypatch):
    monkeypatch.setenv('FX_SOURCE', _fx_file(tmp_path, GOOD_RATES))
    run = client.post('/api/run', json={}).get_json()
    client.post('/api/run', json={})
    client.post('/api/run', json={})
    from app import store
    with store.connection() as db:
        count = db.execute('SELECT COUNT(*) AS n FROM purchase_orders WHERE run_id=?', (run['manifest']['run_id'],)).fetchone()['n']
    assert count == len(run['stages']['6']['rows'])
    assert len(client.get('/api/history').get_json()) == 1


def test_confirm_locks_order_and_rerun_keeps_it(client, tmp_path, monkeypatch):
    monkeypatch.setenv('FX_SOURCE', _fx_file(tmp_path, GOOD_RATES))
    run = client.post('/api/run', json={}).get_json()
    ident = run['manifest']['run_id']
    client.post('/api/review', json={'id': ident, 'revision': 1, 'decision': '通过'})
    from app import store
    orders = store.orders_for_run(ident)
    assert orders and all(o['status'] == '已确认' for o in orders)
    locked = next(o for o in orders if o['currency'] == 'USD')

    # 改汇率快照后重算同一原文：已确认单原币与下单汇率保持不变
    changed = json.loads(json.dumps(GOOD_RATES))
    changed['USD']['2026-11-17'] = '9.9900'
    monkeypatch.setenv('FX_SOURCE', _fx_file(tmp_path, changed))
    rerun = client.post('/api/run', json={}).get_json()
    rows = {r['场景']: r for r in rerun['stages']['6']['rows']}
    kept = rows[locked['canonical']]
    assert kept['采购状态'] == '已确认'
    assert kept['原币金额'] == locked['amount']
    assert kept['下单汇率'] == locked['fx_rate']
    assert kept['折算金额_CNY'] == locked['amount_cny']
    # 差额列反映最新汇率，但不修改锁定成本
    assert kept['重估差额_CNY'] != '0.00'


def test_evidence_exports_original_converted_and_gap(client):
    text = client.get('/api/evidence.csv').data.decode('utf-8-sig')
    for column in ('原币金额', '币种', '下单汇率', '折算金额_CNY', '重估差额_CNY', '采购状态'):
        assert column in text


def test_late_quote_cannot_reverse_confirmed_order(client, tmp_path, monkeypatch):
    monkeypatch.setenv('FX_SOURCE', _fx_file(tmp_path, GOOD_RATES))
    raw = SAMPLE.read_text(encoding='utf-8-sig')
    run = client.post('/api/run', json={'csv': raw}).get_json()
    ident = run['manifest']['run_id']
    client.post('/api/review', json={'id': ident, 'revision': 1, 'decision': '通过'})

    # 追加同场景更便宜的迟到报价
    tail = 'SC0005,,170,172,,,pass,1 USD,2026-11-16T00:00:00Z,2\n'
    later = client.post('/api/run', json={'csv': raw + tail}).get_json()
    rows = later['stages']['6']['rows']
    assert any(r['场景'] == 'SC0005' and r['采购状态'] == '已确认' for r in rows)
    assert any(q['原因码'] == 'STALE_QUOTE' for q in later['quarantine'])
