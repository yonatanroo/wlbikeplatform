import os, sqlite3, json, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# ── ENV ──────────────────────────────────────────────────────────────────────
ADMIN_KEY  = os.getenv("ADMIN_KEY",  "velektro2024")
DB_PATH    = os.getenv("DB_PATH",    "bikes.db")

# Outlook SMTP — stel deze in als env vars op Railway
SMTP_HOST  = os.getenv("SMTP_HOST",  "smtp.office365.com")
SMTP_PORT  = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER  = os.getenv("SMTP_USER",  "")   # jouw Outlook e-mailadres
SMTP_PASS  = os.getenv("SMTP_PASS",  "")   # jouw Outlook wachtwoord
SMTP_FROM  = os.getenv("SMTP_FROM",  SMTP_USER)

# ── APP ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Welease Bike Platform")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ── DB INIT ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS bikes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL, model TEXT NOT NULL, price_orig REAL NOT NULL,
        type_nl TEXT, type_fr TEXT, type_en TEXT, type_tr TEXT, type_ru TEXT,
        desc_nl TEXT, desc_fr TEXT, desc_en TEXT, desc_tr TEXT, desc_ru TEXT,
        sizes TEXT DEFAULT '[]', motor_badge INTEGER DEFAULT 0, img TEXT,
        motor_type TEXT DEFAULT '',
        batteries TEXT DEFAULT '[]',
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
    """)
    conn.commit(); conn.close()

init_db()

# ── DB MIGRATIONS (add new columns to existing databases) ────────────────────
def migrate_db():
    conn = get_db()
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
    motor_type: str=""       # e.g. "Bosch Performance Line CX 85Nm"
    batteries: list=[]       # e.g. ["400Wh", "500Wh", "625Wh"]

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
def row_to_dict(row):
    if row is None: return None
    d = dict(row)
    for k in ["sizes", "languages", "batteries"]:
        if k in d and isinstance(d[k], str):
            try: d[k] = json.loads(d[k])
            except: d[k] = []
    return d

def monthly_price(price_disc):
    return round((price_disc - 500) / 36, 2)

# ── EMAIL ─────────────────────────────────────────────────────────────────────
def send_email(to: str, subject: str, body_html: str):
    """Stuurt een e-mail via Outlook SMTP. Faalt stil als credentials niet ingesteld zijn."""
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
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, [to], msg.as_string())
        print(f"[EMAIL] Verstuurd naar {to}")
    except Exception as e:
        print(f"[EMAIL] Fout bij versturen naar {to}: {e}")

def build_email_html(sub: SubmissionIn) -> str:
    rows = [
        ("Voornaam",        sub.voornaam),
        ("Achternaam",      sub.achternaam),
        ("E-mail",          sub.email),
        ("Telefoon",        sub.tel),
        ("Bedrijf/Afdeling",sub.bedrijf or "–"),
        ("Fiets",           f"{sub.bike_brand} {sub.bike_model}"),
        ("Maat",            sub.maat or "–"),
        ("Gewenste winkel", sub.store_name or "–"),
        ("Betaling",        sub.betaling or "–"),
        ("Klant (slug)",    sub.client_slug),
        ("Opmerkingen",     sub.opmerking or "–"),
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
    return {"expected_length": len(ADMIN_KEY), "first3": ADMIN_KEY[:3] if ADMIN_KEY else ""}

# ════════════════════════════════════════════════════════════════════════════
# BIKES
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/admin/bikes")
async def list_bikes(auth=Depends(require_admin)):
    conn = get_db()
    rows = conn.execute("SELECT * FROM bikes ORDER BY brand,model").fetchall()
    conn.close(); return [row_to_dict(r) for r in rows]

@app.post("/api/admin/bikes", status_code=201)
async def create_bike(bike: BikeIn, auth=Depends(require_admin)):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO bikes (brand,model,price_orig,type_nl,type_fr,type_en,type_tr,type_ru,"
        "desc_nl,desc_fr,desc_en,desc_tr,desc_ru,sizes,motor_badge,img,motor_type,batteries) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (bike.brand,bike.model,bike.price_orig,bike.type_nl,bike.type_fr,bike.type_en,bike.type_tr,bike.type_ru,
         bike.desc_nl,bike.desc_fr,bike.desc_en,bike.desc_tr,bike.desc_ru,json.dumps(bike.sizes),bike.motor_badge,bike.img,
         bike.motor_type,json.dumps(bike.batteries)))
    conn.commit()
    row = conn.execute("SELECT * FROM bikes WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close(); return row_to_dict(row)

@app.put("/api/admin/bikes/{bike_id}")
async def update_bike(bike_id: int, bike: BikeIn, auth=Depends(require_admin)):
    conn = get_db()
    conn.execute(
        "UPDATE bikes SET brand=?,model=?,price_orig=?,type_nl=?,type_fr=?,type_en=?,type_tr=?,type_ru=?,"
        "desc_nl=?,desc_fr=?,desc_en=?,desc_tr=?,desc_ru=?,sizes=?,motor_badge=?,img=?,motor_type=?,batteries=? WHERE id=?",
        (bike.brand,bike.model,bike.price_orig,bike.type_nl,bike.type_fr,bike.type_en,bike.type_tr,bike.type_ru,
         bike.desc_nl,bike.desc_fr,bike.desc_en,bike.desc_tr,bike.desc_ru,json.dumps(bike.sizes),bike.motor_badge,bike.img,
         bike.motor_type,json.dumps(bike.batteries),bike_id))
    conn.commit()
    row = conn.execute("SELECT * FROM bikes WHERE id=?", (bike_id,)).fetchone()
    conn.close()
    if not row: raise HTTPException(404, "Niet gevonden")
    return row_to_dict(row)

@app.delete("/api/admin/bikes/{bike_id}")
async def delete_bike(bike_id: int, auth=Depends(require_admin)):
    conn = get_db()
    conn.execute("DELETE FROM bikes WHERE id=?", (bike_id,)); conn.commit(); conn.close()
    return {"ok": True}

# ════════════════════════════════════════════════════════════════════════════
# CLIENTS
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/admin/clients")
async def list_clients(auth=Depends(require_admin)):
    conn = get_db()
    rows = conn.execute("SELECT * FROM clients ORDER BY name").fetchall()
    conn.close(); return [row_to_dict(r) for r in rows]

@app.post("/api/admin/clients", status_code=201)
async def create_client(client: ClientIn, auth=Depends(require_admin)):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO clients (slug,name,logo_html,primary_color,dark_color,contact_email,languages,active) VALUES (?,?,?,?,?,?,?,?)",
            (client.slug,client.name,client.logo_html,client.primary_color,client.dark_color,
             client.contact_email,json.dumps(client.languages),client.active))
        conn.commit()
        row = conn.execute("SELECT * FROM clients WHERE id=?", (cur.lastrowid,)).fetchone()
        conn.close(); return row_to_dict(row)
    except sqlite3.IntegrityError:
        conn.close(); raise HTTPException(400, "Slug bestaat al")

@app.put("/api/admin/clients/{client_id}")
async def update_client(client_id: int, client: ClientIn, auth=Depends(require_admin)):
    conn = get_db()
    conn.execute(
        "UPDATE clients SET slug=?,name=?,logo_html=?,primary_color=?,dark_color=?,contact_email=?,languages=?,active=? WHERE id=?",
        (client.slug,client.name,client.logo_html,client.primary_color,client.dark_color,
         client.contact_email,json.dumps(client.languages),client.active,client_id))
    conn.commit()
    row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    conn.close()
    if not row: raise HTTPException(404, "Niet gevonden")
    return row_to_dict(row)

@app.delete("/api/admin/clients/{client_id}")
async def delete_client(client_id: int, auth=Depends(require_admin)):
    conn = get_db()
    conn.execute("DELETE FROM clients WHERE id=?", (client_id,)); conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/admin/clients/{client_id}/bikes")
async def list_client_bikes(client_id: int, auth=Depends(require_admin)):
    conn = get_db()
    rows = conn.execute(
        "SELECT b.*, cb.discount_percent FROM bikes b JOIN client_bikes cb ON b.id=cb.bike_id WHERE cb.client_id=? ORDER BY b.brand,b.model",
        (client_id,)).fetchall()
    conn.close(); return [row_to_dict(r) for r in rows]

@app.post("/api/admin/clients/{client_id}/bikes", status_code=201)
async def assign_bike(client_id: int, cb: ClientBikeIn, auth=Depends(require_admin)):
    conn = get_db()
    try:
        conn.execute("INSERT INTO client_bikes (client_id,bike_id,discount_percent) VALUES (?,?,?)",
                     (client_id, cb.bike_id, cb.discount_percent))
    except sqlite3.IntegrityError:
        conn.execute("UPDATE client_bikes SET discount_percent=? WHERE client_id=? AND bike_id=?",
                     (cb.discount_percent, client_id, cb.bike_id))
    conn.commit(); conn.close(); return {"ok": True}

@app.put("/api/admin/clients/{client_id}/bikes/{bike_id}")
async def update_client_bike(client_id: int, bike_id: int, cb: ClientBikeIn, auth=Depends(require_admin)):
    conn = get_db()
    conn.execute("UPDATE client_bikes SET discount_percent=? WHERE client_id=? AND bike_id=?",
                 (cb.discount_percent, client_id, bike_id))
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/admin/clients/{client_id}/bikes/{bike_id}")
async def remove_client_bike(client_id: int, bike_id: int, auth=Depends(require_admin)):
    conn = get_db()
    conn.execute("DELETE FROM client_bikes WHERE client_id=? AND bike_id=?", (client_id, bike_id))
    conn.commit(); conn.close(); return {"ok": True}

@app.get("/api/admin/clients/{client_id}/stores")
async def list_stores(client_id: int, auth=Depends(require_admin)):
    conn = get_db()
    rows = conn.execute("SELECT * FROM client_stores WHERE client_id=? ORDER BY sort_order,id", (client_id,)).fetchall()
    conn.close(); return [row_to_dict(r) for r in rows]

@app.post("/api/admin/clients/{client_id}/stores", status_code=201)
async def create_store(client_id: int, store: StoreIn, auth=Depends(require_admin)):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO client_stores (client_id,city,name,address,phone,email,note,img,sort_order) VALUES (?,?,?,?,?,?,?,?,?)",
        (client_id,store.city,store.name,store.address,store.phone,store.email,store.note,store.img,store.sort_order))
    conn.commit()
    row = conn.execute("SELECT * FROM client_stores WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close(); return row_to_dict(row)

@app.put("/api/admin/clients/{client_id}/stores/{store_id}")
async def update_store(client_id: int, store_id: int, store: StoreIn, auth=Depends(require_admin)):
    conn = get_db()
    conn.execute(
        "UPDATE client_stores SET city=?,name=?,address=?,phone=?,email=?,note=?,img=?,sort_order=? WHERE id=? AND client_id=?",
        (store.city,store.name,store.address,store.phone,store.email,store.note,store.img,store.sort_order,store_id,client_id))
    conn.commit()
    row = conn.execute("SELECT * FROM client_stores WHERE id=?", (store_id,)).fetchone()
    conn.close(); return row_to_dict(row)

@app.delete("/api/admin/clients/{client_id}/stores/{store_id}")
async def delete_store(client_id: int, store_id: int, auth=Depends(require_admin)):
    conn = get_db()
    conn.execute("DELETE FROM client_stores WHERE id=? AND client_id=?", (store_id, client_id))
    conn.commit(); conn.close(); return {"ok": True}

# ════════════════════════════════════════════════════════════════════════════
# SUBMISSIONS  — met automatische e-mail naar winkel
# ════════════════════════════════════════════════════════════════════════════
@app.post("/api/submit", status_code=201)
async def submit_request(sub: SubmissionIn):
    # 1. Opslaan in DB
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO submissions (client_slug,bike_brand,bike_model,store_name,store_email,"
        "voornaam,achternaam,email,tel,bedrijf,maat,betaling,opmerking,lang) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sub.client_slug,sub.bike_brand,sub.bike_model,sub.store_name,sub.store_email,
         sub.voornaam,sub.achternaam,sub.email,sub.tel,sub.bedrijf,sub.maat,sub.betaling,sub.opmerking,sub.lang))
    conn.commit(); sub_id = cur.lastrowid; conn.close()

    # 2. E-mail sturen naar de winkel (als store_email bekend is)
    if sub.store_email:
        subject = f"Nieuwe fietsaanvraag: {sub.bike_brand} {sub.bike_model} – {sub.voornaam} {sub.achternaam}"
        send_email(sub.store_email, subject, build_email_html(sub))

    return {"ok": True, "id": sub_id}

@app.get("/api/admin/submissions")
async def list_submissions(client_slug: Optional[str]=None, status: Optional[str]=None, auth=Depends(require_admin)):
    conn = get_db()
    q = "SELECT * FROM submissions WHERE 1=1"; params = []
    if client_slug: q += " AND client_slug=?"; params.append(client_slug)
    if status:      q += " AND status=?";      params.append(status)
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, params).fetchall(); conn.close()
    return [dict(r) for r in rows]

@app.get("/api/admin/submissions/stats")
async def submission_stats(auth=Depends(require_admin)):
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    new   = conn.execute("SELECT COUNT(*) FROM submissions WHERE status='nieuw'").fetchone()[0]
    done  = conn.execute("SELECT COUNT(*) FROM submissions WHERE status='behandeld'").fetchone()[0]
    by_client = conn.execute("SELECT client_slug, COUNT(*) as cnt FROM submissions GROUP BY client_slug ORDER BY cnt DESC").fetchall()
    conn.close()
    return {"total":total,"new":new,"done":done,"by_client":[dict(r) for r in by_client]}

@app.put("/api/admin/submissions/{sub_id}")
async def update_submission_status(sub_id: int, body: SubmissionStatus, auth=Depends(require_admin)):
    conn = get_db()
    conn.execute("UPDATE submissions SET status=? WHERE id=?", (body.status, sub_id))
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/admin/submissions/{sub_id}")
async def delete_submission(sub_id: int, auth=Depends(require_admin)):
    conn = get_db()
    conn.execute("DELETE FROM submissions WHERE id=?", (sub_id,)); conn.commit(); conn.close()
    return {"ok": True}

# ════════════════════════════════════════════════════════════════════════════
# PUBLIC CLIENT API
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/client/{slug}")
async def get_client_config(slug: str):
    conn = get_db()
    client = conn.execute("SELECT * FROM clients WHERE slug=? AND active=1", (slug,)).fetchone()
    if not client: conn.close(); raise HTTPException(404, f"Client '{slug}' niet gevonden")
    c = row_to_dict(client)
    rows = conn.execute(
        "SELECT b.*, cb.discount_percent FROM bikes b JOIN client_bikes cb ON b.id=cb.bike_id WHERE cb.client_id=? ORDER BY b.brand,b.model",
        (c["id"],)).fetchall()
    bikes = []
    for r in rows:
        b = row_to_dict(r)
        disc = b.get("discount_percent", 0)
        price_disc = round(b["price_orig"] * (1 - disc/100), 2)
        b["priceDisc"] = price_disc
        b["savings"]   = round(b["price_orig"] - price_disc, 2)
        b["monthly"]   = monthly_price(price_disc)
        bikes.append(b)
    stores = conn.execute("SELECT * FROM client_stores WHERE client_id=? ORDER BY sort_order,id", (c["id"],)).fetchall()
    conn.close()
    return {"client": c, "bikes": bikes, "stores": [dict(s) for s in stores]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
