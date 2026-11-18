import sqlite3, json, os, time
from pathlib import Path
from app.errors import DomainError
def connection():
    path=Path(os.environ.get('APP_DB','data/runs.sqlite3'));path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核")')
    db.execute('''CREATE TABLE IF NOT EXISTS purchase_orders(
        run_id TEXT NOT NULL, canonical TEXT NOT NULL, status TEXT NOT NULL DEFAULT "候选",
        currency TEXT NOT NULL, amount TEXT NOT NULL, fx_rate TEXT NOT NULL, amount_cny TEXT NOT NULL,
        quote_date TEXT NOT NULL, gain TEXT NOT NULL, clear_json TEXT NOT NULL DEFAULT "[]",
        created_at TEXT NOT NULL,
        PRIMARY KEY(run_id, canonical))''')
    return db
def save(result):
    with connection() as db:
        ident=result['manifest']['run_id'];row=db.execute('SELECT payload,revision,decision FROM runs WHERE id=?',(ident,)).fetchone()
        if row:
            # 同原文+同规则版本属同一批次：不新增批次与采购单，只刷新计算载荷，
            # 使确认单锁定、汇率回退等跨批次状态在重算后仍可见；复核状态与版本号保留。
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(result,ensure_ascii=False),ident))
            return {**result,'revision':row['revision'],'decision':row['decision'],'reused':True}
        db.execute('INSERT INTO runs(id,payload) VALUES (?,?)',(ident,json.dumps(result,ensure_ascii=False)))
        # 采购单随批次落账；(run_id, canonical) 主键保证同批次重试不新增采购单
        stamp=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        for r in result.get('selected',[]):
            db.execute('''INSERT OR IGNORE INTO purchase_orders
                (run_id,canonical,status,currency,amount,fx_rate,amount_cny,quote_date,gain,clear_json,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (ident,r['canonical'],'候选',r['currency'],str(r['price_n']),str(r['fx_rate']),
                 str(r['amount_cny']),r['quote_date'],str(r['gain']),
                 json.dumps([[str(a),str(z)] for a,z in r['clear']]),stamp))
    return {**result,'revision':1,'decision':'待复核','reused':False}
def get_run(ident):
    with connection() as db: row=db.execute('SELECT payload,revision,decision FROM runs WHERE id=?',(ident,)).fetchone()
    if row is None: raise DomainError('NOT_FOUND','批次不存在',404)
    return {**json.loads(row['payload']),'revision':row['revision'],'decision':row['decision']}
def latest():
    with connection() as db: row=db.execute('SELECT payload,revision,decision FROM runs ORDER BY rowid DESC LIMIT 1').fetchone()
    return {**json.loads(row['payload']),'revision':row['revision'],'decision':row['decision']} if row else None
def history():
    with connection() as db: return [dict(r) for r in db.execute('SELECT id,revision,decision FROM runs ORDER BY rowid DESC')]
def review(ident, revision, decision):
    if decision not in ('通过','退回'): raise DomainError('DECISION','复核动作无效')
    with connection() as db:
        changed=db.execute('UPDATE runs SET revision=revision+1,decision=? WHERE id=? AND revision=?',(decision,ident,revision)).rowcount
        if not changed: raise DomainError('VERSION','版本已变化，请重新载入',409)
        if decision=='通过':
            # 复核通过才确认采购单；原币金额与下单汇率在落账时已锁定，此处只改状态
            db.execute('UPDATE purchase_orders SET status=? WHERE run_id=?',('已确认',ident))
    return {'revision':revision+1,'decision':decision}
def confirmed_orders():
    """全量已确认采购单，同场景取最早确认的一条，键为规范场景号。"""
    with connection() as db:
        rows=db.execute('''SELECT * FROM purchase_orders WHERE status='已确认' ORDER BY rowid ASC''').fetchall()
    return {r['canonical']:dict(r) for r in rows}
def orders_for_run(ident):
    with connection() as db:
        return [dict(r) for r in db.execute('SELECT canonical,status,currency,amount,fx_rate,amount_cny,quote_date,gain,clear_json FROM purchase_orders WHERE run_id=? ORDER BY rowid',(ident,))]
def coverage_for_run(ident):
    """回退路径使用：从台账重建该批次的采购覆盖区间。"""
    with connection() as db:
        rows=db.execute('SELECT clear_json FROM purchase_orders WHERE run_id=?',(ident,)).fetchall()
    spans=[]
    for r in rows:
        spans.extend((json.loads(a),json.loads(z)) for a,z in json.loads(r['clear_json'] or '[]'))
    return spans
