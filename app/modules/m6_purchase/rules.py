import json
import os
from decimal import Decimal

from app.domain import subtract, merge, length
from app.numeric import number
from app.fx import rate_for, convert, FXError, load_snapshot
from app.reasons import isolate


def _latest_snapshot(ctx=None):
    """重估专用：优先用调用方注入的快照，否则每次重新载入最新汇率快照；失败返回None。"""
    if ctx is not None and 'revalue_snapshot' in ctx:
        return ctx.get('revalue_snapshot')
    try:
        return load_snapshot(os.environ.get('FX_SOURCE'))
    except FXError:
        return None


def _revalue_gap(row, latest_snapshot):
    """按最新汇率快照重算与下单时锁定折算额的差额；候选单与CNY恒为0；缺快照时不重估。"""
    if row['order_status'] != '已确认' or row['currency'] == 'CNY' or not latest_snapshot:
        return Decimal('0.00')
    try:
        latest = rate_for(latest_snapshot, row['currency'], row['quote_date'])
    except FXError:
        return Decimal('0.00')
    current = convert(number(row['price_n']), latest)
    return (current - number(row['amount_cny'])).quantize(Decimal('0.01'))


def apply(ctx):
    snapshot = ctx.get('fx_snapshot')
    confirmed = ctx.get('confirmed_orders') or {}
    # 已确认采购单先锁定：保留下单时原币金额与汇率，不参与重算
    selected = []
    covered = []
    cost = Decimal('0.00')
    for canonical, order in confirmed.items():
        locked_clear = [(number(a), number(z)) for a, z in json.loads(order.get('clear_json') or '[]')]
        locked = {
            'canonical': canonical,
            'price_n': number(order['amount']),
            'currency': order['currency'],
            'fx_rate': number(order['fx_rate']),
            'amount_cny': number(order['amount_cny']),
            'quote_date': order['quote_date'],
            'gain': number(order['gain']),
            'clear': locked_clear,
            'order_status': '已确认',
            'run_id': order['run_id'],
        }
        selected.append(locked)
        covered = merge(covered + locked_clear)
        cost += locked['amount_cny']

    candidates = []
    for r in ctx['usable']:
        r = {**r, 'price_n': number(r['price_n']), 'currency': r.get('currency', 'CNY'),
             'quote_date': r.get('quote_date', '')}
        if r['canonical'] in confirmed:
            # 迟到的旧报价（以及任何新报价）都不能倒退已确认采购单
            isolate(ctx, r, 'STALE_QUOTE', '已确认采购单锁定，报价不得倒退')
            continue
        try:
            rate = Decimal('1') if r['currency'] == 'CNY' else rate_for(snapshot, r['currency'], r['quote_date'])
        except FXError as e:
            isolate(ctx, r, 'FX_MISSING', e.message)
            continue
        r['fx_rate'] = rate
        r['amount_cny'] = convert(r['price_n'], rate)
        r['order_status'] = '候选'
        candidates.append(r)

    while candidates:
        ranked = []
        for r in candidates:
            gain = length(subtract(r['clear'], covered))
            score = gain / r['amount_cny'] if r['amount_cny'] else gain * 1000000
            ranked.append((score, gain, r['canonical'], r))
        score, gain, _, best = sorted(ranked, key=lambda x: (-x[0], -x[1], x[2]))[0]
        if gain <= 0:
            break
        candidates.remove(best)
        if cost + best['amount_cny'] > 1000:
            continue
        cost += best['amount_cny']
        covered = merge(covered + best['clear'])
        selected.append({**best, 'gain': gain})

    ctx.update(selected=selected, purchase_coverage=covered, purchase_cost=cost)
    latest_snapshot = _latest_snapshot(ctx)
    rows = []
    for r in selected:
        gap = _revalue_gap(r, latest_snapshot)
        rows.append({
            '场景': r['canonical'],
            '采购状态': r['order_status'],
            '报价日期': r['quote_date'],
            '原币金额': str(r['price_n']),
            '币种': r['currency'],
            '下单汇率': str(r['fx_rate']),
            '折算金额_CNY': str(r['amount_cny']),
            '重估差额_CNY': str(gap),
            '新增覆盖_度': str(r['gain']),
            '性价比': str(r['gain'] / r['amount_cny']) if r['amount_cny'] else '免费',
        })
    gap_total = sum((_revalue_gap(r, latest_snapshot) for r in selected), Decimal('0.00'))
    metrics = [
        ['采购场景', len(rows), '幅'],
        ['采购额', str(cost), 'CNY'],
        ['采购覆盖', str(length(covered)), '度'],
        ['已确认采购单', sum(1 for r in selected if r['order_status'] == '已确认'), '幅'],
        ['汇率来源', (snapshot['source'] + '@' + snapshot['as_of']) if snapshot else '回退旧版', ''],
        ['重估差额合计', str(gap_total), 'CNY'],
    ]
    return {'rows': rows, 'metrics': metrics}
