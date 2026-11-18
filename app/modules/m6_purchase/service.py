import json
import os
from collections import Counter

from app.domain import merge
from app.modules.m6_purchase.rules import apply
from app.numeric import serial, number
from app.fx import load_snapshot, FXError


def _previous_stage6(ctx):
    """同原文的旧版采购候选（历史批次），用于汇率载入失败时整体回退。"""
    from app.store import connection
    digest = ctx['manifest']['sha256']
    try:
        with connection() as db:
            rows = db.execute('SELECT id,payload FROM runs ORDER BY rowid DESC').fetchall()
    except Exception:
        return None, None
    for row in rows:
        payload = json.loads(row['payload'])
        if payload.get('manifest', {}).get('sha256') == digest and payload.get('stages', {}).get('6'):
            return row['id'], payload['stages']['6']
    return None, None


def execute(ctx):
    before = len(ctx['quarantine'])
    from app.store import confirmed_orders
    ctx['confirmed_orders'] = confirmed_orders()
    fallback_reason = None
    try:
        ctx['fx_snapshot'] = load_snapshot(os.environ.get('FX_SOURCE'))
    except FXError as exc:
        previous_id, previous = _previous_stage6(ctx)
        if previous is not None:
            # 汇率载入失败：保留旧版候选，已确认成本不被新汇率改写
            result = serial(previous)
            # 从旧版证据还原下游与落账所需的上下文（原币与下单汇率一并保留）
            legacy = []
            for r in previous.get('rows', []):
                legacy.append({
                    'canonical': r['场景'],
                    'currency': r['币种'],
                    'price_n': number(r['原币金额']),
                    'fx_rate': number(r['下单汇率']),
                    'amount_cny': number(r['折算金额_CNY']),
                    'quote_date': r['报价日期'],
                    'gain': number(r['新增覆盖_度']),
                    'clear': [],
                    'order_status': r['采购状态'],
                })
            from app.store import coverage_for_run
            spans = coverage_for_run(previous_id)
            ctx['selected'] = legacy
            ctx['purchase_cost'] = sum((r['amount_cny'] for r in legacy), number('0'))
            ctx['purchase_coverage'] = merge([(number(a), number(z)) for a, z in spans])
            result['fx_status'] = 'fallback'
            fallback_reason = exc.message
        else:
            # 没有旧版可回退时，以空快照运行（缺汇率的报价逐条隔离），不产出折算候选
            ctx['fx_snapshot'] = None
            result = apply(ctx)
            result['fx_status'] = 'unavailable'
            fallback_reason = exc.message
    else:
        result = apply(ctx)
        result['fx_status'] = 'snapshot'
    result['stage'] = 6
    result['name'] = '采购候选'
    result['issues'] = dict(Counter(row['原因码'] for row in ctx['quarantine']))
    result['new_quarantine'] = len(ctx['quarantine']) - before
    if fallback_reason:
        result['fx_message'] = fallback_reason
        result['metrics'] = result.get('metrics', []) + [['汇率状态', '载入失败·沿用旧版', '']]
        if not any(r.get('原因码') == 'FX_FALLBACK' for r in ctx['quarantine']):
            ctx['quarantine'].append({'原因码': 'FX_FALLBACK', '原因': fallback_reason, '行号': '-'})
    ctx['stages']['6'] = serial(result)
    return ctx
