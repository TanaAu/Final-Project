# ============================================================
# database.py  —  ส่วนจัดการฐานข้อมูล SQLite
# ถูก import ใน app.py / auth.py / shop.py / admin.py ด้วย:
#     from database import get_db
# ============================================================
import sqlite3
from flask import g, current_app
from werkzeug.security import generate_password_hash, check_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(          -- ลูกค้า + ADMIN อยู่ตารางเดียว แยกด้วย is_admin
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT DEFAULT '', phone TEXT DEFAULT '', address TEXT DEFAULT '',
    is_admin INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS products(       -- สินค้า (ADMIN เพิ่ม/แก้/ลบได้)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, brand TEXT DEFAULT '', category TEXT DEFAULT 'Smart Watch',
    color TEXT DEFAULT '', price REAL NOT NULL, description TEXT DEFAULT '',
    image TEXT DEFAULT '', stock INTEGER DEFAULT 10);
CREATE TABLE IF NOT EXISTS orders(         -- หัวใบสั่งซื้อ
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL, total REAL NOT NULL, status TEXT DEFAULT 'pending',   -- pending=รอ ADMIN ตรวจสลิป / paid=อนุมัติแล้ว / rejected=ปฏิเสธ
   
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS order_items(    -- รายการสินค้าในแต่ละใบสั่งซื้อ (เก็บชื่อ/ราคา ณ ตอนซื้อ)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL, product_id INTEGER,
    name TEXT NOT NULL, price REAL NOT NULL, qty INTEGER NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id));
CREATE TABLE IF NOT EXISTS categories(     -- หมวดหมู่สินค้า (ADMIN เพิ่ม/แก้/ลบได้)
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, position INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS product_colors( -- สีของสินค้ารุ่นเดียวกัน (แต่ละสีมีรูปและสต็อกของตัวเอง)
    id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
    color TEXT NOT NULL, image TEXT DEFAULT '', stock INTEGER DEFAULT 10,
    FOREIGN KEY(product_id) REFERENCES products(id));
CREATE TABLE IF NOT EXISTS banners(        -- สไลด์แบนเนอร์หน้าแรก (ADMIN แก้ได้)
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', subtitle TEXT DEFAULT '',
    button_text TEXT DEFAULT '', button_link TEXT DEFAULT '', image TEXT DEFAULT '',
    color TEXT DEFAULT '#0f1420', position INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS comments(       -- คอมเมนต์ลูกค้า (แสดงล่างสุดของหน้าแรก)
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, body TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS widgets(        -- วิดเจ็ต/บล็อกเสริมหน้าแรก (ADMIN เพิ่ม-ลบ-เรียงลำดับได้)
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT DEFAULT 'text', size TEXT DEFAULT 'card',
    title TEXT DEFAULT '', body TEXT DEFAULT '', image TEXT DEFAULT '',
    link_text TEXT DEFAULT '', link TEXT DEFAULT '', position INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS settings(       -- ค่าตั้งค่าร้านที่ ADMIN แก้ได้ เช่น QR ชำระเงิน (key -> value)
    key TEXT PRIMARY KEY, value TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS ban_reasons(    -- สาเหตุการแบนลูกค้า (ADMIN เพิ่ม/ลบได้ภายหลัง)
    id INTEGER PRIMARY KEY AUTOINCREMENT, reason TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS order_events(   -- บันทึกการอัปเดตจัดส่งของแต่ละออเดอร์ (แสดงให้ลูกค้าดู)
    id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, step INTEGER NOT NULL,
    note TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(order_id) REFERENCES orders(id));
"""

def add_col(db, table, col, ddl):
    """migration: เพิ่มคอลัมน์ให้ shop.db เก่า (ถ้ายังไม่มี) โดยข้อมูลเดิมไม่หาย"""
    if col not in [r["name"] for r in db.execute(f"PRAGMA table_info({table})")]:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

# สถานะคำสั่งซื้อ: ลูกค้าอัปโหลดสลิป -> pending -> ADMIN กด อนุมัติ (paid) หรือ ปฏิเสธ (rejected)
# ออเดอร์เก่าที่เป็น 'paid' อยู่แล้ว = ถือว่าอนุมัติแล้ว (ไม่ถูกแตะ)
STATUS_TH = {"pending": "รอตรวจสอบการชำระเงิน", "paid": "ชำระเงินแล้ว", "rejected": "ปฏิเสธ / ไม่ผ่านการตรวจสอบ"}

# ขั้นตอนการจัดส่ง (orders.ship_step: 0 = ยังไม่เริ่ม, 1-3 ตามนี้)
SHIP_STEPS = {1: "รับ Order", 2: "กำลังจัดส่ง", 3: "จัดส่งสำเร็จ"}
DEFAULT_BAN_REASONS = ["ใช้ถ้อยคำไม่สุภาพ / คอมเมนต์ไม่เหมาะสม", "แนบสลิปปลอมหรือหลอกลวง",
                       "สั่งซื้อแล้วไม่ชำระเงินซ้ำ ๆ", "ใช้ข้อมูลเท็จ", "ละเมิดข้อตกลงการใช้งาน"]

def get_setting(db, key, default=""):
    r = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else default

def set_setting(db, key, value):
    db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

def restock_order(db, order_id):
    """คืนสต็อกของออเดอร์ (ใช้ตอน ADMIN ปฏิเสธ): สินค้าที่มีสี -> คืนที่สีนั้น / ไม่มีสี -> คืนที่สินค้าหลัก"""
    for it in db.execute("SELECT product_id, color, qty FROM order_items WHERE order_id=?", (order_id,)).fetchall():
        hit = db.execute("UPDATE product_colors SET stock=stock+? WHERE product_id=? AND color=?",
                         (it["qty"], it["product_id"], it["color"])).rowcount if it["color"] else 0
        if not hit:
            db.execute("UPDATE products SET stock=stock+? WHERE id=?", (it["qty"], it["product_id"]))

def order_lines(db, order_id):
    """รายการสินค้าในออเดอร์ + รูป/แบรนด์/สี (ใช้ค่าที่เก็บตอนซื้อก่อน ถ้าไม่มีใช้ค่าปัจจุบันของสินค้า)"""
    return db.execute("""SELECT oi.id, oi.order_id, oi.product_id, oi.name, oi.price, oi.qty,
        COALESCE(NULLIF(oi.image,''), p.image, '') img, p.brand,
        COALESCE(NULLIF(oi.color,''), p.color, '') color
        FROM order_items oi LEFT JOIN products p ON p.id=oi.product_id WHERE oi.order_id=?""", (order_id,)).fetchall()

# สินค้าตัวอย่าง "ราคา/ชื่อ/รูปเป็นข้อมูลสมมติ" ให้ ADMIN ไปแก้เป็นข้อมูลจริงจากหน้า /admin/products
SAMPLES = [
    ("Apple Watch Series 10 (ตัวอย่าง)", "Apple", "Smart Watch", "Jet Black", 14900),
    ("Samsung Galaxy Watch7 (ตัวอย่าง)", "Samsung", "Smart Watch", "Green", 10900),
    ("Garmin Venu 3 (ตัวอย่าง)", "Garmin", "Sport Watch", "Silver", 15990),
    ("Huawei Watch GT 5 (ตัวอย่าง)", "Huawei", "Smart Watch", "Brown", 7990),
    ("Xiaomi Watch S4 (ตัวอย่าง)", "Xiaomi", "Smart Watch", "Black", 4590),
    ("Amazfit Active 2 (ตัวอย่าง)", "Amazfit", "Smart Band", "Midnight", 3290),
]

# ใช้ทุกที่ที่ดึงสินค้าไปแสดง: ต่อท้ายด้วย " WHERE ..." / " ORDER BY ..." ได้เลย
#   ncolors     = จำนวนสีที่สินค้านี้มี (0 = สินค้าสีเดียว)
#   total_stock = สต็อกรวม (ถ้ามีหลายสี = ผลรวมสต็อกทุกสี)
#   color_img   = รูปของสีแรกที่มีรูป (ใช้เป็นรูปการ์ดเมื่อสินค้าไม่มีรูปหลัก)
PRODUCT_SQL = """SELECT p.*,
  (SELECT COUNT(*) FROM product_colors c WHERE c.product_id=p.id) AS ncolors,
  CASE WHEN EXISTS(SELECT 1 FROM product_colors c WHERE c.product_id=p.id)
       THEN (SELECT COALESCE(SUM(stock),0) FROM product_colors c WHERE c.product_id=p.id) ELSE p.stock END AS total_stock,
  COALESCE((SELECT image FROM product_colors c WHERE c.product_id=p.id AND c.image!='' ORDER BY c.id LIMIT 1),'') AS color_img
  FROM products p"""

def get_db():
    """เปิดการเชื่อมต่อ DB 1 ครั้งต่อ 1 request แล้วใช้ซ้ำ"""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=30)   # ถ้าไฟล์ถูกใช้อยู่ รอได้สูงสุด 30 วินาทีก่อนแจ้ง locked
        g.db.row_factory = sqlite3.Row          # ให้เรียกคอลัมน์ด้วยชื่อ เช่น row["name"]
    return g.db

def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db(app):
    """สร้างตาราง + ADMIN + สินค้าตัวอย่าง (ทำเฉพาะถ้ายังไม่มี) — เรียกจาก app.py"""
    with app.app_context():
        db = get_db(); db.executescript(SCHEMA)
        for c in ("ship_name", "ship_phone", "ship_email", "ship_address"):   # ที่อยู่จัดส่ง ณ ตอนสั่งซื้อ
            add_col(db, "orders", c, "TEXT DEFAULT ''")
        add_col(db, "order_items", "image", "TEXT DEFAULT ''")
        add_col(db, "order_items", "color", "TEXT DEFAULT ''")      # สีที่ลูกค้าซื้อ
        add_col(db, "comments", "author", "TEXT DEFAULT ''")        # ชื่อที่แสดง กรณี ADMIN เพิ่มคอมเมนต์เอง (ว่าง = ใช้ชื่อเจ้าของบัญชี)
        add_col(db, "users", "avatar", "TEXT DEFAULT ''")           # รูปโปรไฟล์ (ลูกค้า + ADMIN)
        add_col(db, "orders", "slip", "TEXT DEFAULT ''")            # ชื่อไฟล์สลิปโอนเงิน (เก็บในโฟลเดอร์ slips/ ไม่เปิดสาธารณะ)
        add_col(db, "orders", "user_order_no", "INTEGER DEFAULT 0")  # เลขคำสั่งซื้อของลูกค้าคนนั้น (#1, #2, ... นับแยกรายคน)
        add_col(db, "orders", "subtotal", "REAL DEFAULT 0")          # ยอดสินค้าก่อน VAT
        add_col(db, "orders", "vat", "REAL DEFAULT 0")               # ภาษีมูลค่าเพิ่ม (บาท) ณ ตอนซื้อ
        add_col(db, "orders", "vat_rate", "REAL DEFAULT 0")          # อัตรา VAT ณ ตอนซื้อ เช่น 0.07 (ออเดอร์เก่าก่อนมี VAT = 0)
        add_col(db, "orders", "reviewed_at", "TEXT DEFAULT ''")       # เวลาที่ ADMIN อนุมัติ/ปฏิเสธ (UTC)
        add_col(db, "orders", "reject_reason", "TEXT DEFAULT ''")     # เหตุผลที่ปฏิเสธ (แสดงให้ลูกค้าเห็น)
        add_col(db, "users", "banned", "INTEGER DEFAULT 0")          # 1 = ถูกแบน (เข้าสู่ระบบไม่ได้)
        add_col(db, "users", "ban_reason", "TEXT DEFAULT ''")        # สาเหตุที่แบน (แสดงให้ลูกค้าเห็น)
        add_col(db, "users", "banned_at", "TEXT DEFAULT ''")
        add_col(db, "orders", "ship_step", "INTEGER DEFAULT 0")      # ขั้นตอนจัดส่งปัจจุบัน 0-3
        if not db.execute("SELECT 1 FROM ban_reasons").fetchone():
            for r in DEFAULT_BAN_REASONS: db.execute("INSERT INTO ban_reasons(reason) VALUES(?)", (r,))
        db.execute("UPDATE orders SET subtotal=total WHERE subtotal=0 AND vat_rate=0")   # ออเดอร์เก่า: ไม่มี VAT ยอดก่อน VAT = ยอดรวมเดิม
        seen = {}                                                     # เติมเลขย้อนหลังให้ออเดอร์เก่า: เรียงตาม id ของแต่ละลูกค้า
        for o in db.execute("SELECT id,user_id,user_order_no FROM orders ORDER BY id").fetchall():
            seen[o["user_id"]] = seen.get(o["user_id"], 0) + 1
            if not o["user_order_no"]:
                db.execute("UPDATE orders SET user_order_no=? WHERE id=?", (seen[o["user_id"]], o["id"]))
        adm = db.execute("SELECT id,username,email,password_hash FROM users WHERE is_admin=1").fetchone()
        if adm:   # มี ADMIN อยู่แล้ว -> ซิงก์ให้ตรง config.py แต่เขียนเฉพาะเมื่อมีอะไรต่างจริง (ลดการล็อกไฟล์ตอนเริ่มโปรแกรม)
            same = (adm["username"] == app.config["ADMIN_USERNAME"] and adm["email"] == app.config["ADMIN_EMAIL"]
                    and check_password_hash(adm["password_hash"], app.config["ADMIN_PASSWORD"]))
            if not same:
                db.execute("UPDATE users SET username=?,email=?,password_hash=? WHERE id=?",
                    (app.config["ADMIN_USERNAME"], app.config["ADMIN_EMAIL"],
                     generate_password_hash(app.config["ADMIN_PASSWORD"]), adm["id"]))
        else:
            db.execute("INSERT INTO users(username,email,password_hash,full_name,is_admin) VALUES(?,?,?,?,1)",
                (app.config["ADMIN_USERNAME"], app.config["ADMIN_EMAIL"],
                 generate_password_hash(app.config["ADMIN_PASSWORD"]), "Administrator"))
        if not db.execute("SELECT 1 FROM products").fetchone():
            for i, (n, b, c, col, p) in enumerate(SAMPLES):
                cur = db.execute("INSERT INTO products(name,brand,category,color,price,description) VALUES(?,?,?,?,?,?)",
                           (n, b, c, col, p, "ข้อมูลตัวอย่าง — ADMIN แก้ไขได้ที่หน้า จัดการสินค้า"))
                if i < 2:   # สองรุ่นแรกใส่หลายสีเป็นตัวอย่าง
                    for cn, st in (("Jet Black", 5), ("Silver", 3), ("Rose Gold", 2)) if i == 0 else (("Green", 4), ("Cream", 6)):
                        db.execute("INSERT INTO product_colors(product_id,color,stock) VALUES(?,?,?)", (cur.lastrowid, cn, st))
        db.execute("INSERT OR IGNORE INTO categories(name) SELECT DISTINCT category FROM products WHERE category!=''")
        for n in ("Smart Watch", "Sport Watch", "Smart Band"):      # หมวดเริ่มต้น (เพิ่ม/ลบ/แก้ที่หน้า ADMIN ได้)
            if not db.execute("SELECT 1 FROM categories").fetchone(): db.execute("INSERT INTO categories(name) VALUES(?)", (n,))
        if not db.execute("SELECT 1 FROM banners").fetchone():
            db.execute("INSERT INTO banners(title,subtitle,position) VALUES('Aor-Au','Smart Watch',1)")
            db.execute("INSERT INTO banners(title,subtitle,button_text,button_link,color,position) VALUES('All Smart Watch','ทุกแบรนด์ ทุกช่วงราคา ในหน้าเดียว','เลือกซื้อสินค้า','/products','#2f4bff',2)")
        if not db.execute("SELECT 1 FROM widgets").fetchone():
            for i, (t, b) in enumerate([("ลูกค้าตัวอย่าง A", "เลือกง่าย ราคาชัดเจน ได้นาฬิกาตรงใจ"), ("ลูกค้าตัวอย่าง B", "สั่งแล้วได้อีเมลใบเสร็จทันที สบายใจ"), ("ลูกค้าตัวอย่าง C", "หน้าเว็บไม่รก หาสินค้าเจอเร็ว")], 1):
                db.execute("INSERT INTO widgets(kind,size,title,body,position) VALUES('quote','card',?,?,?)", (t, b, i))
        db.commit()
