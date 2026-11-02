# ============================================================
# config.py  —  ค่าตั้งต้นทั้งหมดของระบบ (แก้ที่ไฟล์นี้ที่เดียว)
# ถูกเรียกใช้โดย app.py ด้วยคำสั่ง:  app.config.from_object("config")
# ============================================================
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# กุญแจเข้ารหัส session (cookie ล็อกอิน) — ควรเปลี่ยนเป็นค่าสุ่มของตัวเอง
SECRET_KEY = os.environ.get("SECRET_KEY", "aor-au-change-this-secret")

# ไฟล์ฐานข้อมูล SQLite (ข้อมูลอยู่ถาวร ปิด cmd แล้วเปิดใหม่ก็ยังอยู่)
DATABASE = os.path.join(BASE_DIR, "shop.db")

# โฟลเดอร์เก็บรูปที่ ADMIN อัปโหลด
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}

# ---------- บัญชี ADMIN เริ่มต้น (สร้างอัตโนมัติครั้งแรก) ----------
ADMIN_USERNAME = "Au80"
ADMIN_PASSWORD = "Au1234"          # ในฐานข้อมูลจะเก็บเป็น hash ไม่เก็บตัวจริง
ADMIN_EMAIL = "tanakornousonean@gmail.com"

# ---------- ภาษีมูลค่าเพิ่ม (VAT) ----------
# ราคาสินค้าที่ ADMIN ตั้งไว้ = "ราคาก่อน VAT" ระบบบวก VAT ให้อัตโนมัติทุกสินค้า/ทุกการชำระเงิน
VAT_PERCENT = 7
VAT_RATE = VAT_PERCENT / 100

# ---------- การส่งอีเมลผ่าน Gmail (SMTP) ----------
# ต้องใช้ "App Password" 16 หลักของ Gmail (ไม่ใช่รหัสผ่านปกติ) ดูวิธีใน README.md
# ตั้งค่าผ่าน environment variable เพื่อไม่ฝังรหัสไว้ในโค้ด:
#   Windows:  set SMTP_USER=you@gmail.com   และ   set SMTP_PASS=xxxxxxxxxxxxxxxx
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_USER = os.environ.get("SMTP_USER", ADMIN_EMAIL)
SMTP_PASS = os.environ.get("SMTP_PASS", "")   # ว่าง = ไม่ส่งจริง แค่พิมพ์ลง cmd

# ---------- รูปโปรไฟล์ / สลิปโอนเงิน ----------
MAX_CONTENT_LENGTH = 16 * 1024 * 1024        # ไฟล์ที่อัปโหลดต่อครั้งไม่เกิน 16 MB
SLIP_FOLDER = os.path.join(BASE_DIR, "slips")  # สลิปเก็บนอก static -> เปิดดูได้เฉพาะเจ้าของออเดอร์และ ADMIN
SLIP_EXT = {"png", "jpg", "jpeg", "webp"}
