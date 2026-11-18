import json
from copy import deepcopy
from decimal import Decimal

import pytest

from app.fx import load_snapshot
from app.modules.m6_purchase.rules import apply
from app.numeric import number


def _usable(canonical, price, currency, day, clear, gain=None):
    return {
        'canonical': canonical, 'price_n': number(price), 'currency': currency,
        'quote_date': day, 'clear': clear, '行号': 1,
    }


def _ctx(rows, confirmed=None):
    return {'usable': rows, 'quarantine': [], 'fx_snapshot': load_snapshot(),
            'confirmed_orders': confirmed or {}}


def test_usd_uses_quote_date_snapshot_rate():
    ctx = _ctx([_usable('SCX', '100', 'USD', '2026-11-17', [(Decimal('170'), Decimal('172'))])])
    result = apply(ctx)
    row = result['rows'][0]
    assert row['币种'] == 'USD'
    assert row['下单汇率'] == '7.1200'
    assert row['原币金额'] == '100'
    assert row['折算金额_CNY'] == '712.00'
    assert row['重估差额_CNY'] == '0.00'


def test_same_scene_ranking_uses_cny_equivalent():
    # 20 USD @7.12 = 142.4 CNY，比 150 CNY 更便宜，应优先选 USD 报价
    cny = _usable('CNYSCENE', '150', 'CNY', '2026-11-17', [(Decimal('170'), Decimal('172'))])
    usd = _usable('USDSCENE', '20', 'USD', '2026-11-17', [(Decimal('170'), Decimal('172'))])
    ctx = _ctx([cny, usd])
    result = apply(ctx)
    assert result['rows'][0]['场景'] == 'USDSCENE'
    assert number(result['rows'][0]['折算金额_CNY']) == Decimal('142.40')


def test_missing_rate_quarantines_instead_of_guessing():
    row = _usable('NORATE', '18', 'USD', '2026-11-19', [(Decimal('172'), Decimal('174'))])
    ctx = _ctx([row])
    result = apply(ctx)
    assert result['rows'] == []
    assert ctx['quarantine'][0]['原因码'] == 'FX_MISSING'


def test_confirmed_order_locks_original_amount_and_rate(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DB', str(tmp_path / 'db.sqlite3'))
    from app import store
    order = {
        'run_id': 'oldrun', 'canonical': 'LOCKED', 'status': '已确认', 'currency': 'USD',
        'amount': '100', 'fx_rate': '7.0800', 'amount_cny': '708.00',
        'quote_date': '2026-11-15', 'gain': '2', 'clear_json': '[[170, 172]]',
    }
    with store.connection() as db:
        db.execute('''INSERT INTO purchase_orders
            (run_id,canonical,status,currency,amount,fx_rate,amount_cny,quote_date,gain,clear_json,created_at)
            VALUES (:run_id,:canonical,:status,:currency,:amount,:fx_rate,:amount_cny,:quote_date,:gain,:clear_json,'t')''', order)
    confirmed = store.confirmed_orders()
    # 新报价更便宜（按最新汇率折算 10*7.12=71.2）也不能倒退已确认单
    new_quote = _usable('LOCKED', '10', 'USD', '2026-11-17', [(Decimal('170'), Decimal('172'))])
    ctx = _ctx([new_quote], confirmed=confirmed)
    result = apply(ctx)
    locked = result['rows'][0]
    assert locked['采购状态'] == '已确认'
    assert locked['原币金额'] == '100'
    assert locked['下单汇率'] == '7.0800'
    assert locked['折算金额_CNY'] == '708.00'
    assert any(q['原因码'] == 'STALE_QUOTE' for q in ctx['quarantine'])


def test_revaluation_gap_against_latest_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DB', str(tmp_path / 'db.sqlite3'))
    from app import store
    order = {
        'run_id': 'oldrun', 'canonical': 'LOCKED', 'status': '已确认', 'currency': 'USD',
        'amount': '100', 'fx_rate': '7.0800', 'amount_cny': '708.00',
        'quote_date': '2026-11-15', 'gain': '2', 'clear_json': '[[170, 172]]',
    }
    with store.connection() as db:
        db.execute('''INSERT INTO purchase_orders
            (run_id,canonical,status,currency,amount,fx_rate,amount_cny,quote_date,gain,clear_json,created_at)
            VALUES (:run_id,:canonical,:status,:currency,:amount,:fx_rate,:amount_cny,:quote_date,:gain,:clear_json,'t')''', order)
    ctx = _ctx([], confirmed=store.confirmed_orders())
    # 注入与下单日不同的最新快照：11-15 最新价 7.10，锁定汇率 7.08
    ctx['revalue_snapshot'] = {'rates': {'USD': {'2026-11-15': Decimal('7.1000')}}}
    result = apply(ctx)
    # 最新快照 2026-11-15 为 7.10，重估 710.00，差额 +2.00；锁定折算额仍为 708.00
    assert result['rows'][0]['折算金额_CNY'] == '708.00'
    assert result['rows'][0]['重估差额_CNY'] == '2.00'
    assert result['metrics'][-1][1] == '2.00'


def test_cny_revaluation_gap_is_zero():
    row = _usable('CNYSCENE', '100', 'CNY', '2026-11-17', [(Decimal('170'), Decimal('172'))])
    result = apply(_ctx([row]))
    assert result['rows'][0]['重估差额_CNY'] == '0.00'


def test_empty_snapshot_isolates_all_fx_rows():
    row = _usable('USDSCENE', '20', 'USD', '2026-11-17', [(Decimal('170'), Decimal('172'))])
    ctx = {'usable': [row], 'quarantine': [], 'fx_snapshot': None, 'confirmed_orders': {}}
    result = apply(ctx)
    assert result['rows'] == []
    assert ctx['quarantine'][0]['原因码'] == 'FX_MISSING'


def test_determinism_unchanged_with_currency(monkeypatch, tmp_path):
    monkeypatch.setenv('APP_DB', str(tmp_path / 'db.sqlite3'))
    from app.pipeline import calculate
    first = calculate()
    second = calculate()
    assert [r['场景'] for r in first['stages']['6']['rows']] == [r['场景'] for r in second['stages']['6']['rows']]
