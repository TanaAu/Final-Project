Remove-Item -Recurse -Force .git -ErrorAction SilentlyContinue# ============================================================
# app.py  —  ไฟล์หลัก "รันไฟล์นี้ไฟล์เดียว"   ->   python app.py
# ทำหน้าที่ประกอบทุกไฟล์เข้าด้วยกัน:
#   config.py   -> app.config.from_object("config")
#   database.py -> init_db(app) / close_db
#   auth.py, shop.py, admin.py -> app.register_blueprint(...)   (เชื่อมแต่ละส่วนเป็นหน้าเว็บ)
#   templates/*.html -> ถูกเรียกด้วย render_template("ชื่อไฟล์.html")
# ============================================================
import os
from datetime import datetime, timedelta
from flask import Flask, session, g, flash, redirect, request
from database import init_db, close_db, get_db, STATUS_TH, SHIP_STEPS
from auth import auth_bp
from shop import shop_bp
from admin import admin_bp

app = Flask(__name__)
app.config.from_object("config")                 # โหลดค่าจาก config.py
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

app.teardown_appcontext(close_db)                # ปิด DB เมื่อจบ request
app.register_blueprint(auth_bp)                  # เชื่อม: สมัคร/ล็อกอิน
app.register_blueprint(shop_bp)                  # เชื่อม: หน้าร้าน
app.register_blueprint(admin_bp)                 # เชื่อม: หลังบ้าน ADMIN
init_db(app)                                     # สร้างตาราง + ADMIN ครั้งแรก

@app.before_request
def load_user():
    """ทุก request: ดูว่าใครล็อกอินอยู่ (จาก session) แล้วเก็บไว้ใน g.user ให้ template ใช้"""
    uid = session.get("uid")
    g.user = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if g.user and g.user["banned"] and not g.user["is_admin"]:     # ลูกค้าที่ถูกแบน: ล้าง session ทันที ใช้งานต่อไม่ได้
        reason = g.user["ban_reason"]; session.clear(); g.user = None
        flash("บัญชีของคุณถูกระงับการใช้งาน" + (f" — สาเหตุ: {reason}" if reason else ""), "warn")

app.jinja_env.globals["SHIP_STEPS"] = SHIP_STEPS               # ขั้นตอนจัดส่ง ใช้ใน template
app.jinja_env.globals["VAT_PERCENT"] = app.config["VAT_PERCENT"]   # ใช้ได้ทุก template รวมถึง macro ใน _card.html

@app.context_processor
def inject():
    """ส่งตัวแปรให้ทุก template: จำนวนสินค้าในตะกร้า"""
    return {"cart_count": sum(session.get("cart", {}).values())}

@app.template_filter("baht")
def baht(v): return f"{v:,.0f}"

@app.template_filter("money")
def money(v):
    """จำนวนเงินที่อาจมีสตางค์ (VAT / ยอดรวม): ไม่มีเศษแสดงเต็มบาท มีเศษแสดง 2 ตำแหน่ง"""
    v = round(float(v or 0), 2)
    return f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"

@app.template_filter("vat_amt")
def vat_amt(v):
    """VAT ของราคา (ก่อน VAT) ที่ส่งเข้ามา"""
    return round(float(v or 0) * app.config["VAT_RATE"], 2)

@app.template_filter("incl_vat")
def incl_vat(v):
    """ราคารวม VAT"""
    return round(float(v or 0) * (1 + app.config["VAT_RATE"]), 2)

@app.template_filter("status_th")
def status_th(v):
    """'pending' -> 'รอตรวจสอบการชำระเงิน' ฯลฯ"""
    return STATUS_TH.get(v, v)

THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

@app.template_filter("thai_dt")
def thai_dt(v):
    """'2026-10-14 09:30:00' (เวลา UTC ใน DB) -> '14 ต.ค. 2569 16:30' (เวลาไทย + พ.ศ.)"""
    try: d = datetime.strptime(str(v)[:19], "%Y-%m-%d %H:%M:%S") + timedelta(hours=7)
    except ValueError: return v
    return f"{d.day} {THAI_MONTHS[d.month - 1]} {d.year + 543} {d:%H:%M}"

@app.errorhandler(413)
def too_large(e):
    """อัปโหลดไฟล์ใหญ่เกิน MAX_CONTENT_LENGTH ใน config.py"""
    flash("ไฟล์ใหญ่เกินไป (สูงสุด 16 MB) กรุณาเลือกไฟล์ที่เล็กลง", "warn")
    return redirect(request.referrer or "/")

if __name__ == "__main__":
    app.run(debug=True)                          # เปิดที่ http://127.0.0.1:5000
