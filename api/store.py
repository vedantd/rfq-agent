"""Local SQLite persistence with per-tenant record scoping."""
import json, os, sqlite3
import database


def connection():
    path=os.getenv('RFQ_DB_PATH','quote_api.sqlite3')
    conn=sqlite3.connect(path,timeout=5)
    conn.row_factory=sqlite3.Row
    return conn


def init():
    with connection() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS rfqs
          (id TEXT PRIMARY KEY, tenant TEXT NOT NULL, idempotency_key TEXT, payload TEXT NOT NULL)''')
        con.execute('''CREATE UNIQUE INDEX IF NOT EXISTS rfqs_idempotency
          ON rfqs(tenant,idempotency_key) WHERE idempotency_key IS NOT NULL''')
        con.execute('''CREATE TABLE IF NOT EXISTS catalog
          (tenant TEXT NOT NULL, sku TEXT NOT NULL, payload TEXT NOT NULL,
          PRIMARY KEY (tenant,sku))''')
        con.execute('''CREATE TABLE IF NOT EXISTS quotes
          (id TEXT PRIMARY KEY, tenant TEXT NOT NULL, rfq_id TEXT NOT NULL, payload TEXT NOT NULL)''')


def load_catalog(tenant):
    with connection() as con:
        for item in database.load_catalog():
            con.execute('INSERT OR IGNORE INTO catalog(tenant,sku,payload) VALUES(?,?,?)',
                        (tenant,item['sku'],json.dumps(item)))
        rows=con.execute('SELECT payload FROM catalog WHERE tenant=? ORDER BY sku',(tenant,)).fetchall()
    return [json.loads(r['payload']) for r in rows]


def upsert_catalog(tenant,item):
    with connection() as con:
        con.execute('INSERT OR REPLACE INTO catalog VALUES(?,?,?)',(tenant,item['sku'],json.dumps(item)))


def get_rfq(tenant,rfq_id):
    with connection() as con:
        row=con.execute('SELECT payload FROM rfqs WHERE tenant=? AND id=?',(tenant,rfq_id)).fetchone()
    return json.loads(row['payload']) if row else None


def save_rfq(rfq):
    with connection() as con:
        con.execute('''INSERT INTO rfqs(id,tenant,idempotency_key,payload) VALUES(?,?,?,?)
          ON CONFLICT(id) DO UPDATE SET payload=excluded.payload''',
          (rfq['id'],rfq['tenant_id'],rfq.get('idempotency_key'),json.dumps(rfq)))


def find_idempotent(tenant,key):
    with connection() as con:
        row=con.execute('SELECT payload FROM rfqs WHERE tenant=? AND idempotency_key=?',(tenant,key)).fetchone()
    return json.loads(row['payload']) if row else None


def save_quote(q):
    with connection() as con:
        con.execute('INSERT INTO quotes VALUES(?,?,?,?)',(q['id'],q['tenant_id'],q['rfq_id'],json.dumps(q)))


def get_quote(tenant,qid):
    with connection() as con:
        row=con.execute('SELECT payload FROM quotes WHERE tenant=? AND id=?',(tenant,qid)).fetchone()
    return json.loads(row['payload']) if row else None
