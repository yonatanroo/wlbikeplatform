import os, json, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# ── ENV ──────────────────────────────────────────────────────────────────────
ADMIN_KEY    = os.getenv("ADMIN_KEY",    "velektro2024")
DATABASE_URL = os.getenv("DATABASE_URL", "")          # Railway PostgreSQL zet dit automatisch
DB_PATH      = os.getenv("DB_PATH",      "bikes.db")  # SQLite fallback (lokale dev)
USE_PG       = bool(DATABASE_URL)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row
else:
    import sqlite3

# ── APP ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Welease Bike Platform")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ── DB HELPERS ───────────────────────────────────────────────────────────────
def get_db():
    if USE_PG:
        return psycopg.connect(DATABASE_URL)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _exec(conn, sql, params=()):
    """Execute sql on whichever DB is active."""
    if USE_PG:
        cur = conn.cursor(row_factory=dict_row)
        cur.execute(sql, params)
        return cur
    else:
        return conn.execute(sql.replace("%s", "?"), params)

def db_fetchall(conn, sql, params=()):
    return [dict(r) for r in _exec(conn, sql, params).fetchall()]

def db_fetchone(conn, sql, params=()):
    row = _exec(conn, sql, params).fetchone()
    return dict(row) if row else None

def db_insert(conn, sql, params):
    """INSERT and return the new id."""
    if USE_PG:
        cur = conn.cursor(row_factory=dict_row)
        cur.execute(sql + " RETURNING id", params)
        conn.commit()
        return cur.fetchone()["id"]
    cur = conn.execute(sql.replace("%s", "?"), params)
    conn.commit()
    return cur.lastrowid

def db_run(conn, sql, params=()):
    _exec(conn, sql, params)
    conn.commit()

def parse_row(row):
    if row is None: return None
    d = dict(row)
    for k in ["sizes", "languages", "batteries"]:
        if k in d and isinstance(d[k], str):
            try: d[k] = json.loads(d[k])
            except: d[k] = []
    return d

def db_fetchall_p(conn, sql, params=()):
    return [parse_row(r) for r in db_fetchall(conn, sql, params)]

def db_fetchone_p(conn, sql, params=()):
    return parse_row(db_fetchone(conn, sql, params))

# ── SCHEMA ───────────────────────────────────────────────────────────────────
PG_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS bikes (
        id SERIAL PRIMARY KEY,
        brand TEXT NOT NULL, model TEXT NOT NULL, price_orig REAL NOT NULL,
        type_nl TEXT DEFAULT '', type_fr TEXT DEFAULT '', type_en TEXT DEFAULT '',
        type_tr TEXT DEFAULT '', type_ru TEXT DEFAULT '',
        desc_nl TEXT DEFAULT '', desc_fr TEXT DEFAULT '', desc_en TEXT DEFAULT '',
        desc_tr TEXT DEFAULT '', desc_ru TEXT DEFAULT '',
        sizes TEXT DEFAULT '[]', motor_badge INTEGER DEFAULT 0, img TEXT,
        motor_type TEXT DEFAULT '', batteries TEXT DEFAULT '[]',
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS clients (
        id SERIAL PRIMARY KEY,
        slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, logo_html TEXT DEFAULT '',
        primary_color TEXT DEFAULT '#2d8f4e', dark_color TEXT DEFAULT '#1a3a2a',
        contact_email TEXT DEFAULT '', languages TEXT DEFAULT '["nl"]',
        active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS client_bikes (
        id SERIAL PRIMARY KEY,
        client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
        bike_id INTEGER REFERENCES bikes(id) ON DELETE CASCADE,
        discount_percent REAL DEFAULT 0,
        UNIQUE(client_id, bike_id)
    )""",
    """CREATE TABLE IF NOT EXISTS client_stores (
        id SERIAL PRIMARY KEY,
        client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
        city TEXT NOT NULL, name TEXT DEFAULT '', address TEXT DEFAULT '',
        phone TEXT DEFAULT '', email TEXT DEFAULT '', note TEXT DEFAULT '',
        img TEXT, sort_order INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS submissions (
        id SERIAL PRIMARY KEY,
        client_slug TEXT, bike_brand TEXT DEFAULT '', bike_model TEXT DEFAULT '',
        store_name TEXT DEFAULT '', store_email TEXT DEFAULT '',
        voornaam TEXT, achternaam TEXT, email TEXT, tel TEXT,
        bedrijf TEXT DEFAULT '', maat TEXT DEFAULT '', betaling TEXT DEFAULT '',
        opmerking TEXT DEFAULT '', lang TEXT DEFAULT 'nl', status TEXT DEFAULT 'nieuw',
        created_at TIMESTAMP DEFAULT NOW()
    )""",
]

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS bikes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL, model TEXT NOT NULL, price_orig REAL NOT NULL,
    type_nl TEXT, type_fr TEXT, type_en TEXT, type_tr TEXT, type_ru TEXT,
    desc_nl TEXT, desc_fr TEXT, desc_en TEXT, desc_tr TEXT, desc_ru TEXT,
    sizes TEXT DEFAULT '[]', motor_badge INTEGER DEFAULT 0, img TEXT,
    motor_type TEXT DEFAULT '', batteries TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, logo_html TEXT,
    primary_color TEXT DEFAULT '#2d8f4e', dark_color TEXT DEFAULT '#1a3a2a',
    contact_email TEXT, languages TEXT DEFAULT '["nl"]',
    active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS client_bikes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    bike_id INTEGER REFERENCES bikes(id) ON DELETE CASCADE,
    discount_percent REAL DEFAULT 0,
    UNIQUE(client_id, bike_id)
);
CREATE TABLE IF NOT EXISTS client_stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    city TEXT NOT NULL, name TEXT, address TEXT,
    phone TEXT, email TEXT, note TEXT, img TEXT, sort_order INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_slug TEXT, bike_brand TEXT, bike_model TEXT,
    store_name TEXT, store_email TEXT,
    voornaam TEXT, achternaam TEXT, email TEXT, tel TEXT,
    bedrijf TEXT, maat TEXT, betaling TEXT, opmerking TEXT,
    lang TEXT DEFAULT 'nl', status TEXT DEFAULT 'nieuw',
    created_at TEXT DEFAULT (datetime('now'))
);
"""

def init_db():
    conn = get_db()
    if USE_PG:
        cur = conn.cursor()
        for stmt in PG_SCHEMA:
            cur.execute(stmt)
        conn.commit()
    else:
        conn.executescript(SQLITE_SCHEMA)
    conn.close()

init_db()

# ── DB MIGRATIONS ─────────────────────────────────────────────────────────────
def migrate_db():
    conn = get_db()
    if USE_PG:
        cur = conn.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='bikes'")
        existing = [r[0] for r in cur.fetchall()]
        if "motor_type" not in existing:
            cur.execute("ALTER TABLE bikes ADD COLUMN motor_type TEXT DEFAULT ''")
        if "batteries" not in existing:
            cur.execute("ALTER TABLE bikes ADD COLUMN batteries TEXT DEFAULT '[]'")
        conn.commit()
    else:
        existing = [row[1] for row in conn.execute("PRAGMA table_info(bikes)").fetchall()]
        if "motor_type" not in existing:
            conn.execute("ALTER TABLE bikes ADD COLUMN motor_type TEXT DEFAULT ''")
        if "batteries" not in existing:
            conn.execute("ALTER TABLE bikes ADD COLUMN batteries TEXT DEFAULT '[]'")
        conn.commit()
    conn.close()

migrate_db()

# ── AUTH ─────────────────────────────────────────────────────────────────────
def require_admin(x_api_key: Optional[str] = Header(None)):
    if x_api_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

# ── MODELS ───────────────────────────────────────────────────────────────────
class BikeIn(BaseModel):
    brand: str; model: str; price_orig: float
    type_nl: str=""; type_fr: str=""; type_en: str=""; type_tr: str=""; type_ru: str=""
    desc_nl: str=""; desc_fr: str=""; desc_en: str=""; desc_tr: str=""; desc_ru: str=""
    sizes: list=[]; motor_badge: int=0; img: Optional[str]=None
    motor_type: str=""; batteries: list=[]

class ClientIn(BaseModel):
    slug: str; name: str; logo_html: str=""
    primary_color: str="#2d8f4e"; dark_color: str="#1a3a2a"
    contact_email: str=""; languages: list=["nl"]; active: int=1

class ClientBikeIn(BaseModel):
    bike_id: int; discount_percent: float=0

class StoreIn(BaseModel):
    city: str; name: str=""; address: str=""; phone: str=""
    email: str=""; note: str=""; img: Optional[str]=None; sort_order: int=0

class SubmissionIn(BaseModel):
    client_slug: str
    bike_brand: str=""; bike_model: str=""
    store_name: str=""; store_email: str=""
    voornaam: str; achternaam: str; email: str; tel: str
    bedrijf: str=""; maat: str=""; betaling: str=""; opmerking: str=""
    lang: str="nl"

class SubmissionStatus(BaseModel):
    status: str

# ── HELPERS ──────────────────────────────────────────────────────────────────
def monthly_price(price_disc):
    return round((price_disc - 500) / 36, 2)

# ── EMAIL ─────────────────────────────────────────────────────────────────────
def send_email(to: str, subject: str, body_html: str):
    if not SMTP_USER or not SMTP_PASS:
        print(f"[EMAIL] SMTP niet geconfigureerd — mail naar {to} niet verstuurd.")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_FROM
        msg["To"]      = to
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo(); server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, [to], msg.as_string())
        print(f"[EMAIL] Verstuurd naar {to}")
    except Exception as e:
        print(f"[EMAIL] Fout bij versturen naar {to}: {e}")

def build_email_html(sub: SubmissionIn) -> str:
    rows = [
        ("Voornaam",         sub.voornaam),
        ("Achternaam",       sub.achternaam),
        ("E-mail",           sub.email),
        ("Telefoon",         sub.tel),
        ("Bedrijf/Afdeling", sub.bedrijf or "–"),
        ("Fiets",            f"{sub.bike_brand} {sub.bike_model}"),
        ("Maat",             sub.maat or "–"),
        ("Gewenste winkel",  sub.store_name or "–"),
        ("Betaling",         sub.betaling or "–"),
        ("Klant (slug)",     sub.client_slug),
        ("Opmerkingen",      sub.opmerking or "–"),
    ]
    rows_html = "".join(
        f"<tr><td style='padding:8px 12px;font-weight:600;color:#456;background:#f7fbf9;white-space:nowrap'>{k}</td>"
        f"<td style='padding:8px 12px;color:#222'>{v}</td></tr>"
        for k, v in rows
    )
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <div style="background:#2db37a;padding:20px 28px;border-radius:12px 12px 0 0">
        <h2 style="color:#fff;margin:0;font-size:20px">🚲 Nieuwe fietsaanvraag</h2>
        <p style="color:rgba(255,255,255,.85);margin:6px 0 0;font-size:13px">
          Via het Welease Bike Platform – klant: <strong>{sub.client_slug}</strong>
        </p>
      </div>
      <table style="width:100%;border-collapse:collapse;border:1px solid #ddefea;border-top:none">
        {rows_html}
      </table>
      <p style="font-size:11px;color:#aaa;margin-top:14px;text-align:center">
        Welease Bike Platform · Beheer via
        <a href="https://web-production-44ea4.up.railway.app" style="color:#2db37a">
          web-production-44ea4.up.railway.app
        </a>
      </p>
    </div>"""

# ── STATIC ───────────────────────────────────────────────────────────────────
ADMIN_HTML = os.path.join(os.path.dirname(__file__), "admin.html")

@app.get("/", response_class=HTMLResponse)
@app.get("/admin", response_class=HTMLResponse)
async def serve_admin():
    try:
        with open(ADMIN_HTML) as f: return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>admin.html niet gevonden</h1>", status_code=404)

@app.post("/api/auth/verify")
async def verify_auth(x_api_key: Optional[str] = Header(None)):
    if x_api_key == ADMIN_KEY: return {"ok": True}
    raise HTTPException(status_code=401, detail="Verkeerde sleutel")

@app.get("/api/debug/key")
async def debug_key():
    return {"expected_length": len(ADMIN_KEY), "first3": ADMIN_KEY[:3] if ADMIN_KEY else "", "use_pg": USE_PG}

# ════════════════════════════════════════════════════════════════════════════
# BACKUP / RESTORE  — zodat data nooit verloren gaat
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/admin/backup")
async def backup_db(auth=Depends(require_admin)):
    """Exporteer alle data als JSON — sla dit regelmatig op als veiligheid."""
    conn = get_db()
    data = {
        "bikes":        db_fetchall_p(conn, "SELECT * FROM bikes"),
        "clients":      db_fetchall_p(conn, "SELECT * FROM clients"),
        "client_bikes": db_fetchall(conn,   "SELECT * FROM client_bikes"),
        "client_stores":db_fetchall(conn,   "SELECT * FROM client_stores"),
        "submissions":  db_fetchall(conn,   "SELECT * FROM submissions"),
    }
    conn.close()
    return data

# ════════════════════════════════════════════════════════════════════════════
# BIKES
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/admin/bikes")
async def list_bikes(auth=Depends(require_admin)):
    conn = get_db()
    rows = db_fetchall_p(conn, "SELECT * FROM bikes ORDER BY brand,model")
    conn.close(); return rows

@app.post("/api/admin/bikes", status_code=201)
async def create_bike(bike: BikeIn, auth=Depends(require_admin)):
    conn = get_db()
    new_id = db_insert(conn,
        "INSERT INTO bikes (brand,model,price_orig,type_nl,type_fr,type_en,type_tr,type_ru,"
        "desc_nl,desc_fr,desc_en,desc_tr,desc_ru,sizes,motor_badge,img,motor_type,batteries) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (bike.brand,bike.model,bike.price_orig,bike.type_nl,bike.type_fr,bike.type_en,bike.type_tr,bike.type_ru,
         bike.desc_nl,bike.desc_fr,bike.desc_en,bike.desc_tr,bike.desc_ru,json.dumps(bike.sizes),bike.motor_badge,bike.img,
         bike.motor_type,json.dumps(bike.batteries)))
    row = db_fetchone_p(conn, "SELECT * FROM bikes WHERE id=%s", (new_id,))
    conn.close(); return row

@app.put("/api/admin/bikes/{bike_id}")
async def update_bike(bike_id: int, bike: BikeIn, auth=Depends(require_admin)):
    conn = get_db()
    db_run(conn,
        "UPDATE bikes SET brand=%s,model=%s,price_orig=%s,type_nl=%s,type_fr=%s,type_en=%s,type_tr=%s,type_ru=%s,"
        "desc_nl=%s,desc_fr=%s,desc_en=%s,desc_tr=%s,desc_ru=%s,sizes=%s,motor_badge=%s,img=%s,motor_type=%s,batteries=%s WHERE id=%s",
        (bike.brand,bike.model,bike.price_orig,bike.type_nl,bike.type_fr,bike.type_en,bike.type_tr,bike.type_ru,
         bike.desc_nl,bike.desc_fr,bike.desc_en,bike.desc_tr,bike.desc_ru,json.dumps(bike.sizes),bike.motor_badge,bike.img,
         bike.motor_type,json.dumps(bike.batteries),bike_id))
    row = db_fetchone_p(conn, "SELECT * FROM bikes WHERE id=%s", (bike_id,))
    conn.close()
    if not row: raise HTTPException(404, "Niet gevonden")
    return row

@app.delete("/api/admin/bikes/{bike_id}")
async def delete_bike(bike_id: int, auth=Depends(require_admin)):
    conn = get_db()
    db_run(conn, "DELETE FROM bikes WHERE id=%s", (bike_id,))
    conn.close(); return {"ok": True}

# ════════════════════════════════════════════════════════════════════════════
# CLIENTS
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/admin/clients")
async def list_clients(auth=Depends(require_admin)):
    conn = get_db()
    rows = db_fetchall_p(conn, "SELECT * FROM clients ORDER BY name")
    conn.close(); return rows

@app.post("/api/admin/clients", status_code=201)
async def create_client(client: ClientIn, auth=Depends(require_admin)):
    conn = get_db()
    try:
        new_id = db_insert(conn,
            "INSERT INTO clients (slug,name,logo_html,primary_color,dark_color,contact_email,languages,active) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (client.slug,client.name,client.logo_html,client.primary_color,client.dark_color,
             client.contact_email,json.dumps(client.languages),client.active))
        row = db_fetchone_p(conn, "SELECT * FROM clients WHERE id=%s", (new_id,))
        conn.close(); return row
    except Exception:
        conn.rollback(); conn.close()
        raise HTTPException(400, "Slug bestaat al")

@app.put("/api/admin/clients/{client_id}")
async def update_client(client_id: int, client: ClientIn, auth=Depends(require_admin)):
    conn = get_db()
    db_run(conn,
        "UPDATE clients SET slug=%s,name=%s,logo_html=%s,primary_color=%s,dark_color=%s,"
        "contact_email=%s,languages=%s,active=%s WHERE id=%s",
        (client.slug,client.name,client.logo_html,client.primary_color,client.dark_color,
         client.contact_email,json.dumps(client.languages),client.active,client_id))
    row = db_fetchone_p(conn, "SELECT * FROM clients WHERE id=%s", (client_id,))
    conn.close()
    if not row: raise HTTPException(404, "Niet gevonden")
    return row

@app.delete("/api/admin/clients/{client_id}")
async def delete_client(client_id: int, auth=Depends(require_admin)):
    conn = get_db()
    db_run(conn, "DELETE FROM clients WHERE id=%s", (client_id,))
    conn.close(); return {"ok": True}

@app.get("/api/admin/clients/{client_id}/bikes")
async def list_client_bikes(client_id: int, auth=Depends(require_admin)):
    conn = get_db()
    rows = db_fetchall_p(conn,
        "SELECT b.*, cb.discount_percent FROM bikes b "
        "JOIN client_bikes cb ON b.id=cb.bike_id WHERE cb.client_id=%s ORDER BY b.brand,b.model",
        (client_id,))
    conn.close(); return rows

@app.post("/api/admin/clients/{client_id}/bikes", status_code=201)
async def assign_bike(client_id: int, cb: ClientBikeIn, auth=Depends(require_admin)):
    conn = get_db()
    try:
        db_insert(conn,
            "INSERT INTO client_bikes (client_id,bike_id,discount_percent) VALUES (%s,%s,%s)",
            (client_id, cb.bike_id, cb.discount_percent))
    except Exception:
        conn.rollback()
        db_run(conn,
            "UPDATE client_bikes SET discount_percent=%s WHERE client_id=%s AND bike_id=%s",
            (cb.discount_percent, client_id, cb.bike_id))
    conn.close(); return {"ok": True}

@app.put("/api/admin/clients/{client_id}/bikes/{bike_id}")
async def update_client_bike(client_id: int, bike_id: int, cb: ClientBikeIn, auth=Depends(require_admin)):
    conn = get_db()
    db_run(conn,
        "UPDATE client_bikes SET discount_percent=%s WHERE client_id=%s AND bike_id=%s",
        (cb.discount_percent, client_id, bike_id))
    conn.close(); return {"ok": True}

@app.delete("/api/admin/clients/{client_id}/bikes/{bike_id}")
async def remove_client_bike(client_id: int, bike_id: int, auth=Depends(require_admin)):
    conn = get_db()
    db_run(conn, "DELETE FROM client_bikes WHERE client_id=%s AND bike_id=%s", (client_id, bike_id))
    conn.close(); return {"ok": True}

@app.get("/api/admin/clients/{client_id}/stores")
async def list_stores(client_id: int, auth=Depends(require_admin)):
    conn = get_db()
    rows = db_fetchall(conn,
        "SELECT * FROM client_stores WHERE client_id=%s ORDER BY sort_order,id", (client_id,))
    conn.close(); return rows

@app.post("/api/admin/clients/{client_id}/stores", status_code=201)
async def create_store(client_id: int, store: StoreIn, auth=Depends(require_admin)):
    conn = get_db()
    new_id = db_insert(conn,
        "INSERT INTO client_stores (client_id,city,name,address,phone,email,note,img,sort_order) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (client_id,store.city,store.name,store.address,store.phone,store.email,store.note,store.img,store.sort_order))
    row = db_fetchone(conn, "SELECT * FROM client_stores WHERE id=%s", (new_id,))
    conn.close(); return row

@app.put("/api/admin/clients/{client_id}/stores/{store_id}")
async def update_store(client_id: int, store_id: int, store: StoreIn, auth=Depends(require_admin)):
    conn = get_db()
    db_run(conn,
        "UPDATE client_stores SET city=%s,name=%s,address=%s,phone=%s,email=%s,note=%s,img=%s,sort_order=%s "
        "WHERE id=%s AND client_id=%s",
        (store.city,store.name,store.address,store.phone,store.email,store.note,store.img,store.sort_order,store_id,client_id))
    row = db_fetchone(conn, "SELECT * FROM client_stores WHERE id=%s", (store_id,))
    conn.close(); return row

@app.delete("/api/admin/clients/{client_id}/stores/{store_id}")
async def delete_store(client_id: int, store_id: int, auth=Depends(require_admin)):
    conn = get_db()
    db_run(conn, "DELETE FROM client_stores WHERE id=%s AND client_id=%s", (store_id, client_id))
    conn.close(); return {"ok": True}

# ════════════════════════════════════════════════════════════════════════════
# SUBMISSIONS
# ════════════════════════════════════════════════════════════════════════════
@app.post("/api/submit", status_code=201)
async def submit_request(sub: SubmissionIn):
    conn = get_db()
    new_id = db_insert(conn,
        "INSERT INTO submissions (client_slug,bike_brand,bike_model,store_name,store_email,"
        "voornaam,achternaam,email,tel,bedrijf,maat,betaling,opmerking,lang) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (sub.client_slug,sub.bike_brand,sub.bike_model,sub.store_name,sub.store_email,
         sub.voornaam,sub.achternaam,sub.email,sub.tel,sub.bedrijf,sub.maat,sub.betaling,sub.opmerking,sub.lang))
    conn.close()
    if sub.store_email:
        subject = f"Nieuwe fietsaanvraag: {sub.bike_brand} {sub.bike_model} – {sub.voornaam} {sub.achternaam}"
        send_email(sub.store_email, subject, build_email_html(sub))
    return {"ok": True, "id": new_id}

@app.get("/api/admin/submissions")
async def list_submissions(client_slug: Optional[str]=None, status: Optional[str]=None, auth=Depends(require_admin)):
    conn = get_db()
    q = "SELECT * FROM submissions WHERE 1=1"; params = []
    if client_slug: q += " AND client_slug=%s"; params.append(client_slug)
    if status:      q += " AND status=%s";      params.append(status)
    q += " ORDER BY created_at DESC"
    rows = db_fetchall(conn, q, params)
    conn.close(); return rows

@app.get("/api/admin/submissions/stats")
async def submission_stats(auth=Depends(require_admin)):
    conn = get_db()
    total      = db_fetchone(conn, "SELECT COUNT(*) as n FROM submissions")["n"]
    new        = db_fetchone(conn, "SELECT COUNT(*) as n FROM submissions WHERE status='nieuw'")["n"]
    done       = db_fetchone(conn, "SELECT COUNT(*) as n FROM submissions WHERE status='behandeld'")["n"]
    by_client  = db_fetchall(conn, "SELECT client_slug, COUNT(*) as cnt FROM submissions GROUP BY client_slug ORDER BY cnt DESC")
    conn.close()
    return {"total": total, "new": new, "done": done, "by_client": by_client}

@app.put("/api/admin/submissions/{sub_id}")
async def update_submission_status(sub_id: int, body: SubmissionStatus, auth=Depends(require_admin)):
    conn = get_db()
    db_run(conn, "UPDATE submissions SET status=%s WHERE id=%s", (body.status, sub_id))
    conn.close(); return {"ok": True}

@app.delete("/api/admin/submissions/{sub_id}")
async def delete_submission(sub_id: int, auth=Depends(require_admin)):
    conn = get_db()
    db_run(conn, "DELETE FROM submissions WHERE id=%s", (sub_id,))
    conn.close(); return {"ok": True}

# ════════════════════════════════════════════════════════════════════════════
# PUBLIC CLIENT API
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/client/{slug}")
async def get_client_config(slug: str):
    conn = get_db()
    client = db_fetchone_p(conn, "SELECT * FROM clients WHERE slug=%s AND active=1", (slug,))
    if not client:
        conn.close(); raise HTTPException(404, f"Client '{slug}' niet gevonden")
    rows = db_fetchall_p(conn,
        "SELECT b.*, cb.discount_percent FROM bikes b "
        "JOIN client_bikes cb ON b.id=cb.bike_id WHERE cb.client_id=%s ORDER BY b.brand,b.model",
        (client["id"],))
    bikes = []
    for b in rows:
        disc = b.get("discount_percent", 0)
        price_disc = round(b["price_orig"] * (1 - disc/100), 2)
        b["priceDisc"] = price_disc
        b["savings"]   = round(b["price_orig"] - price_disc, 2)
        b["monthly"]   = monthly_price(price_disc)
        bikes.append(b)
    stores = db_fetchall(conn,
        "SELECT * FROM client_stores WHERE client_id=%s ORDER BY sort_order,id", (client["id"],))
    conn.close()
    return {"client": client, "bikes": bikes, "stores": stores}

@app.get("/api/clients")
async def list_active_clients():
    conn = get_db()
    rows = db_fetchall(conn, "SELECT slug, name FROM clients WHERE active=1 ORDER BY name")
    conn.close(); return rows

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
