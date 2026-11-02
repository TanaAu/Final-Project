# ============================================================
# auth.py  —  สมัครสมาชิก / ล็อกอิน / ล็อกเอาต์ (ลูกค้าและ ADMIN)
# ถูกเชื่อมเข้าแอปใน app.py ด้วย:  app.register_blueprint(auth_bp)
# ============================================================
import re, time
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db

auth_bp = Blueprint("auth", __name__)

# ---------- ตรวจชื่อ / อีเมล Gmail / เบอร์โทร (ใช้ร่วมกันทั้งตอนสมัครและตอนแก้โปรไฟล์) ----------
def check_contact(name, email, phone):
    """คืนข้อความ error ถ้าไม่ผ่าน / None ถ้าผ่าน
    - ชื่อ-นามสกุล: ห้ามว่าง
    - อีเมล: ต้องเป็น Gmail (ลงท้าย @gmail.com) — ถ้าจะรับอีเมลอื่นด้วย ให้แก้ regexp บรรทัดนี้
    - เบอร์โทร: ตัวเลข 0-9 เท่านั้น ยาว 9-10 หลัก (ห้ามมี - เว้นวรรค หรือตัวอักษร)"""
    if not (name or "").strip():
        return "กรุณากรอกชื่อ-นามสกุล"
    if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@gmail\.com", (email or "").strip().lower()):
        return "อีเมลต้องเป็น Gmail เท่านั้น เช่น name@gmail.com"
    if not re.fullmatch(r"[0-9]{9,10}", (phone or "").strip()):
        return "เบอร์โทรต้องเป็นตัวเลขเท่านั้น 9-10 หลัก (ไม่ต้องใส่ - หรือเว้นวรรค)"
    return None

# ---------- กติการหัสผ่าน (ใช้ทั้งตอนสมัครและตอนตั้งรหัสใหม่) ----------
def check_password(p):
    """ตรวจรหัสผ่านตามกติกา คืนข้อความ error ถ้าไม่ผ่าน / คืน None ถ้าผ่าน
    กติกา: ยาวอย่างน้อย 6 ตัว, มีตัวพิมพ์ใหญ่ A-Z อย่างน้อย 1, มีตัวพิมพ์เล็ก a-z อย่างน้อย 1,
           ตัวเลขใส่กี่ตัวก็ได้ (เลขติดกันกี่ตัวก็ผ่าน)"""
    if len(p) < 6:
        return "รหัสผ่านต้องยาวอย่างน้อย 6 ตัว"
    if not re.search(r"[A-Z]", p):
        return "รหัสผ่านต้องมีตัวพิมพ์ใหญ่ (A-Z) อย่างน้อย 1 ตัว"
    if not re.search(r"[a-z]", p):
        return "รหัสผ่านต้องมีตัวพิมพ์เล็ก (a-z) อย่างน้อย 1 ตัว"
    return None

# ---------- ตัวตรวจสิทธิ์ (ใช้เป็น @login_required / @admin_required บนฟังก์ชันหน้าเว็บ) ----------
def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not g.user:
            flash("กรุณาเข้าสู่ระบบก่อน"); return redirect(url_for("auth.login", next=request.path))
        return f(*a, **k)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if not g.user or not g.user["is_admin"]:
            flash("กรุณาเข้าสู่ระบบก่อน"); return redirect(url_for("auth.login"))   # ไม่เปิดเผยทางเข้า ADMIN
        return f(*a, **k)
    return w

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        u, e, p = f.get("username", "").strip(), f.get("email", "").strip().lower(), f.get("password", "")
        name, phone = f.get("full_name", "").strip(), f.get("phone", "").strip()
        # 1) ช่องบังคับ 5 ช่อง: ขาดอย่างใดอย่างหนึ่ง = ไม่ให้สมัคร และบอกว่าขาดอะไรบ้าง
        missing = [lb for lb, v in (("ชื่อผู้ใช้", u), ("อีเมล (Gmail)", e), ("รหัสผ่าน", p),
                                     ("ชื่อ-นามสกุล", name), ("เบอร์โทร", phone)) if not v]
        if missing:
            flash("กรุณากรอกข้อมูลให้ครบ ยังขาด: " + ", ".join(missing), "warn")
        else:
            # 2) ตรวจรูปแบบ: Gmail, เบอร์โทรตัวเลขล้วน, ความแข็งแรงรหัสผ่าน
            err = check_contact(name, e, phone) or check_password(p)
            if err:
                flash(err, "warn")
            else:
                db = get_db()
                if db.execute("SELECT 1 FROM users WHERE username=? OR email=?", (u, e)).fetchone():
                    flash("ชื่อผู้ใช้หรืออีเมลนี้ถูกใช้แล้ว", "warn")
                else:
                    cur = db.execute("INSERT INTO users(username,email,password_hash,full_name,phone,address) VALUES(?,?,?,?,?,?)",
                        (u, e, generate_password_hash(p), name, phone, f.get("address", "").strip()))
                    db.commit(); session["uid"] = cur.lastrowid   # session = จำว่าใครล็อกอินอยู่
                    return redirect(url_for("shop.home"))
    return render_template("register.html", f=request.form)   # ส่งค่าเดิมกลับไป กรอกซ้ำไม่ต้องพิมพ์ใหม่

# ---------- คำสั่งลับเปิดหน้าล็อกอิน ADMIN ----------
# พิมพ์คำสั่งนี้ในช่อง "ชื่อผู้ใช้ หรือ อีเมล" ของหน้าล็อกอินลูกค้า แล้วกดเข้าสู่ระบบ -> จะเปิดหน้าล็อกอิน ADMIN
# (เปลี่ยนคำสั่งได้ที่ตัวแปรนี้ / หน้า ADMIN ไม่มีลิงก์ที่ไหนในเว็บเลย)
ADMIN_SECRET_CMD = "/gamemode 1"
ADMIN_GATE_SECONDS = 600           # ประตูเปิดอยู่ 10 นาที แล้วต้องพิมพ์คำสั่งใหม่

def admin_gate_open():
    """True ถ้าเพิ่งพิมพ์คำสั่งลับมาภายใน 10 นาที (เก็บใน session ของเบราว์เซอร์นั้น)"""
    return time.time() - session.get("admin_gate", 0) < ADMIN_GATE_SECONDS

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        key = request.form["login"].strip()          # ใช้ได้ทั้ง username หรือ อีเมล
        if " ".join(key.lower().split()) == ADMIN_SECRET_CMD:      # คำสั่งลับ -> เปิดประตู ADMIN
            session["admin_gate"] = time.time()
            return redirect(url_for("auth.admin_login"))
        user = get_db().execute("SELECT * FROM users WHERE (username=? OR email=?) AND is_admin=0",
                                (key, key.lower())).fetchone()   # ลูกค้าเท่านั้น: ADMIN ล็อกอินที่หน้าลับ
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            if user["banned"]:                                   # ถูกแบน: ไม่ให้เข้าสู่ระบบ และบอกสาเหตุ
                flash("บัญชีนี้ถูกระงับการใช้งาน" + (f" — สาเหตุ: {user['ban_reason']}" if user["ban_reason"] else "") + " หากคิดว่าเกิดความผิดพลาด กรุณาติดต่อร้าน", "warn")
                return render_template("login.html", admin=False)
            session["uid"] = user["id"]
            return redirect(request.args.get("next") or url_for("shop.home"))
        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    return render_template("login.html", admin=False)

@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not admin_gate_open():                        # ไม่ได้พิมพ์คำสั่งลับ -> เหมือนไม่มีหน้านี้ ส่งกลับหน้าล็อกอินลูกค้า
        session.pop("admin_gate", None)
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        user = get_db().execute("SELECT * FROM users WHERE username=? AND is_admin=1", (request.form["login"].strip(),)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form["password"]):
            session.pop("admin_gate", None)
            session["uid"] = user["id"]; return redirect(url_for("admin.dashboard"))
        flash("ID หรือรหัสผ่าน ADMIN ไม่ถูกต้อง")
    return render_template("login.html", admin=True)

@auth_bp.route("/logout")
def logout():
    session.clear(); return redirect(url_for("shop.home"))


# ---------- ลืมรหัสผ่าน: ตรวจสอบ อีเมล + เบอร์โทร ให้ตรงกับที่สมัครไว้ แล้วจึงตั้งรหัสใหม่ได้ ----------
def norm_phone(p):
    """เก็บเฉพาะตัวเลข เพื่อให้ 081-234-5678 กับ 0812345678 ถือว่าเป็นเบอร์เดียวกัน"""
    return re.sub(r"\D", "", p or "")

@auth_bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        tries = session.get("forgot_tries", 0)
        if tries >= 5:                                   # กันการไล่เดาข้อมูล: ผิดได้ไม่เกิน 5 ครั้งต่อเบราว์เซอร์
            flash("กรอกผิดหลายครั้งเกินไป กรุณาลองใหม่ภายหลัง"); return render_template("forgot.html")
        email, phone = request.form["email"].strip().lower(), norm_phone(request.form["phone"])
        user = get_db().execute("SELECT * FROM users WHERE email=? AND is_admin=0", (email,)).fetchone()
        if user and phone and norm_phone(user["phone"]) == phone:     # อีเมลและเบอร์ต้องตรงทั้งคู่
            session.pop("forgot_tries", None)
            session["reset_uid"], session["reset_at"] = user["id"], time.time()   # อนุญาตตั้งรหัสใหม่ 10 นาที
            return redirect(url_for("auth.reset_password"))
        session["forgot_tries"] = tries + 1
        flash("อีเมลหรือเบอร์โทรไม่ตรงกับข้อมูลที่สมัครไว้")   # ไม่บอกว่าผิดช่องไหน
    return render_template("forgot.html")

@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if not uid or time.time() - session.get("reset_at", 0) > 600:    # ต้องผ่านขั้นตอนตรวจสอบมาก่อน และไม่เกิน 10 นาที
        session.pop("reset_uid", None); flash("กรุณายืนยันตัวตนใหม่"); return redirect(url_for("auth.forgot"))
    if request.method == "POST":
        p1, p2 = request.form["password"], request.form["password2"]
        err = check_password(p1)
        if err: flash(err, "warn")
        elif p1 != p2: flash("รหัสผ่านทั้งสองช่องไม่ตรงกัน", "warn")
        else:
            db = get_db(); db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(p1), uid)); db.commit()
            session.pop("reset_uid", None); session.pop("reset_at", None)
            flash("ตั้งรหัสผ่านใหม่แล้ว กรุณาเข้าสู่ระบบ"); return redirect(url_for("auth.login"))
    return render_template("reset.html")
