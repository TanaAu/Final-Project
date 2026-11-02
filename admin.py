# ============================================================
# admin.py  —  หลังบ้านสำหรับ ADMIN (ต้องล็อกอินที่ /admin/login)
# เพิ่ม / แก้ไข / ลบสินค้า, ดูลูกค้าทั้งหมด และสินค้าที่ลูกค้าแต่ละคนซื้อ
# ถูกเชื่อมเข้าแอปใน app.py ด้วย:  app.register_blueprint(admin_bp)
# ============================================================
import os, uuid
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, g
from database import get_db, order_lines, restock_order, PRODUCT_SQL, STATUS_TH, SHIP_STEPS, get_setting, set_setting
from uploads import save_qr, delete_qr
import reports
from mailer import send_mail
from auth import admin_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

@admin_bp.context_processor
def inject_pending():
    """ส่ง pending_count ให้ทุกหน้า ADMIN (ใช้โชว์ตัวเลขที่เมนู 'คำสั่งซื้อ')"""
    if g.get("user") and g.user["is_admin"]:
        return {"pending_count": get_db().execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]}
    return {"pending_count": 0}

@admin_bp.route("/")
@admin_required
def dashboard():
    db = get_db()
    s = db.execute("""SELECT (SELECT COUNT(*) FROM products) p, (SELECT COUNT(*) FROM users WHERE is_admin=0) u,
                      (SELECT COUNT(*) FROM orders) o, (SELECT COALESCE(SUM(total),0) FROM orders WHERE status='paid') r,
                      (SELECT COUNT(*) FROM orders WHERE status='pending') pend,
                      (SELECT COUNT(*) FROM categories) c,
                      (SELECT COUNT(*) FROM banners WHERE active=1) b, (SELECT COUNT(*) FROM widgets WHERE active=1) w,
                      (SELECT COUNT(*) FROM comments) cm""").fetchone()
    today = db.execute(f"SELECT COUNT(*) n, COALESCE(SUM(o.total),0) r FROM orders o WHERE o.status='paid' AND {THAI_DAY}=?", (thai_today().isoformat(),)).fetchone()
    ship_wait = db.execute("SELECT COUNT(*) FROM orders WHERE status='paid' AND ship_step<3").fetchone()[0]
    return render_template("admin/dashboard.html", s=s, today=today, ov=reports.overview_report(db, thai_today()), ship_wait=ship_wait)

# ---------- จัดการสินค้า ----------
@admin_bp.route("/products")
@admin_required
def products():
    return render_template("admin/products.html", items=get_db().execute(PRODUCT_SQL + " ORDER BY p.id DESC"))

def store_upload(f):
    """บันทึกไฟล์รูปที่อัปโหลด (ถ้านามสกุลอนุญาต) ตั้งชื่อใหม่ด้วย uuid แล้วคืนพาธ / ไม่มีไฟล์คืน ''"""
    if f and f.filename and f.filename.rsplit(".", 1)[-1].lower() in current_app.config["ALLOWED_EXT"]:
        name = uuid.uuid4().hex + "." + f.filename.rsplit(".", 1)[-1].lower()
        f.save(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
        return "/static/uploads/" + name
    return ""

def save_image(default=""):
    """รับรูปจากไฟล์อัปโหลด หรือจาก URL (อย่างใดอย่างหนึ่ง) ถ้าไม่มีทั้งคู่ใช้ค่าเดิม"""
    return store_upload(request.files.get("image_file")) or request.form.get("image_url", "").strip() or default

def category_names(db):
    return [r["name"] for r in db.execute("SELECT name FROM categories ORDER BY position, name")]

@admin_bp.route("/products/new", methods=["GET", "POST"])
@admin_bp.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def product_form(pid=None):
    db = get_db()
    p = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone() if pid else None
    colors = db.execute("SELECT * FROM product_colors WHERE product_id=? ORDER BY id", (pid,)).fetchall() if pid else []
    if request.method == "POST":
        f = request.form
        try: price, stock = float(f["price"]), int(f.get("stock") or 0)
        except ValueError:
            flash("ราคาและสต็อกต้องเป็นตัวเลข"); return redirect(request.url)
        # หมวดหมู่: เลือกจากรายการ หรือพิมพ์ชื่อใหม่ (จะถูกสร้างเป็นหมวดใหม่อัตโนมัติ)
        cat = f.get("new_category", "").strip() or f.get("category", "")
        if cat: db.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (cat,))
        vals = (f["name"], f["brand"], cat, f["color"], price, f["description"], save_image(p["image"] if p else ""), stock)
        if p: db.execute("UPDATE products SET name=?,brand=?,category=?,color=?,price=?,description=?,image=?,stock=? WHERE id=?", vals + (pid,))
        else: pid = db.execute("INSERT INTO products(name,brand,category,color,price,description,image,stock) VALUES(?,?,?,?,?,?,?,?)", vals).lastrowid
        # ---- ตัวเลือกสี: แต่ละแถวในฟอร์ม = 1 สี (ชื่อ / สต็อก / รูป) จัดเรียงตามลำดับแถว ----
        ids, names, stocks = f.getlist("color_id"), f.getlist("color_name"), f.getlist("color_stock")
        urls, files = f.getlist("color_image_url"), request.files.getlist("color_image_file")
        old = {str(r["id"]): r for r in db.execute("SELECT * FROM product_colors WHERE product_id=?", (pid,))}
        keep, seen = set(), set()
        for i, nm in enumerate(names):
            nm = nm.strip()
            if not nm or nm.lower() in seen: continue             # ข้ามแถวว่าง / ชื่อสีซ้ำ
            seen.add(nm.lower())
            try: st = max(int(stocks[i] or 0), 0) if i < len(stocks) else 0
            except ValueError: st = 0
            prev = old.get(ids[i]) if i < len(ids) else None
            img = (store_upload(files[i]) if i < len(files) else "") or (urls[i].strip() if i < len(urls) else "") or (prev["image"] if prev else "")
            if prev:
                db.execute("UPDATE product_colors SET color=?,stock=?,image=? WHERE id=?", (nm, st, img, prev["id"])); keep.add(str(prev["id"]))
            else:
                keep.add(str(db.execute("INSERT INTO product_colors(product_id,color,stock,image) VALUES(?,?,?,?)", (pid, nm, st, img)).lastrowid))
        for cid in old:                                              # แถวที่ ADMIN ลบออกจากฟอร์ม = ลบสีนั้น
            if cid not in keep: db.execute("DELETE FROM product_colors WHERE id=?", (cid,))
        db.commit(); flash("บันทึกสินค้าแล้ว"); return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", p=p, colors=colors, cats=category_names(db))

@admin_bp.route("/products/<int:pid>/delete", methods=["POST"])
@admin_required
def product_delete(pid):
    db = get_db(); db.execute("DELETE FROM product_colors WHERE product_id=?", (pid,)); db.execute("DELETE FROM products WHERE id=?", (pid,)); db.commit()
    flash("ลบสินค้าแล้ว"); return redirect(url_for("admin.products"))

# ---------- หมวดหมู่สินค้า: เพิ่ม / เปลี่ยนชื่อ / ลบ ----------
@admin_bp.route("/categories", methods=["GET", "POST"])
@admin_required
def categories():
    db = get_db()
    if request.method == "POST":                                     # เพิ่มหมวดใหม่
        name = request.form.get("name", "").strip()
        if not name: flash("กรุณาพิมพ์ชื่อหมวดหมู่")
        elif db.execute("SELECT 1 FROM categories WHERE name=?", (name,)).fetchone(): flash("มีหมวดหมู่นี้อยู่แล้ว")
        else:
            db.execute("INSERT INTO categories(name,position) VALUES(?,?)", (name, request.form.get("position", type=int, default=0))); db.commit()
            flash("เพิ่มหมวดหมู่แล้ว")
        return redirect(url_for("admin.categories"))
    rows = db.execute("""SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category=c.name) n
                         FROM categories c ORDER BY c.position, c.name""").fetchall()
    return render_template("admin/categories.html", rows=rows)

@admin_bp.route("/categories/<int:cid>/rename", methods=["POST"])
@admin_required
def category_rename(cid):
    db = get_db(); c = db.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone()
    new = request.form.get("name", "").strip()
    if c and new and new != c["name"]:
        if db.execute("SELECT 1 FROM categories WHERE name=?", (new,)).fetchone(): flash("มีหมวดหมู่ชื่อนี้อยู่แล้ว")
        else:
            db.execute("UPDATE products SET category=? WHERE category=?", (new, c["name"]))     # สินค้าในหมวดเดิมย้ายตามชื่อใหม่
            db.execute("UPDATE categories SET name=? WHERE id=?", (new, cid)); db.commit(); flash("เปลี่ยนชื่อหมวดหมู่แล้ว")
    return redirect(url_for("admin.categories"))

@admin_bp.route("/categories/<int:cid>/delete", methods=["POST"])
@admin_required
def category_delete(cid):
    db = get_db(); c = db.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone()
    if c and db.execute("SELECT 1 FROM products WHERE category=?", (c["name"],)).fetchone():
        flash(f"ลบไม่ได้: ยังมีสินค้าอยู่ในหมวด {c['name']} (ย้ายหรือลบสินค้าก่อน)")
    elif c:
        db.execute("DELETE FROM categories WHERE id=?", (cid,)); db.commit(); flash("ลบหมวดหมู่แล้ว")
    return redirect(url_for("admin.categories"))

# ---------- ลูกค้า + รายการที่ซื้อ ----------
@admin_bp.route("/users")
@admin_required
def users():
    """หน้าลูกค้าแบ่ง 2 แถบ: ?tab=ban (แบนลูกค้า) / ?tab=ship (อัปเดตการจัดส่ง ?ship=active|done|all)"""
    db = get_db(); tab = request.args.get("tab", "ban")
    if tab not in ("ban", "ship"): tab = "ban"
    ctx = dict(tab=tab, pending_ship=db.execute("SELECT COUNT(*) FROM orders WHERE status='paid' AND ship_step<3").fetchone()[0])
    if tab == "ban":
        ctx["rows"] = db.execute("""SELECT u.*, COUNT(o.id) n, COALESCE(SUM(CASE WHEN o.status='paid' THEN o.total END),0) spent FROM users u
            LEFT JOIN orders o ON o.user_id=u.id WHERE u.is_admin=0 GROUP BY u.id ORDER BY u.banned DESC, u.id DESC""").fetchall()
        ctx["reasons"] = db.execute("SELECT * FROM ban_reasons ORDER BY id").fetchall()
    else:
        flt = request.args.get("ship", "active")
        where = {"active": " AND o.ship_step<3", "done": " AND o.ship_step=3"}.get(flt, ""); ctx["flt"] = flt if flt in ("active", "done") else "all"
        ctx["rows"] = db.execute("SELECT o.*, u.username FROM orders o JOIN users u ON u.id=o.user_id WHERE o.status='paid'" + where + " ORDER BY o.id DESC").fetchall()
        ctx["ev"] = {o["id"]: db.execute("SELECT * FROM order_events WHERE order_id=? ORDER BY id DESC LIMIT 3", (o["id"],)).fetchall() for o in ctx["rows"]}
    return render_template("admin/users.html", **ctx)

# ---------- 3.1 แบนลูกค้า (เลือกสาเหตุจากรายการ + เพิ่มสาเหตุใหม่ได้ภายหลัง) ----------
@admin_bp.route("/users/<int:uid>/ban", methods=["POST"])
@admin_required
def user_ban(uid):
    db = get_db(); u = db.execute("SELECT * FROM users WHERE id=? AND is_admin=0", (uid,)).fetchone()
    r = db.execute("SELECT reason FROM ban_reasons WHERE id=?", (request.form.get("reason_id", type=int, default=0),)).fetchone()
    if not u: flash("ไม่พบลูกค้า", "warn")
    elif not r: flash("กรุณาเลือกสาเหตุที่แบน", "warn")
    else:
        note = request.form.get("note", "").strip()[:200]
        db.execute("UPDATE users SET banned=1, ban_reason=?, banned_at=datetime('now') WHERE id=?", (r["reason"] + (f" ({note})" if note else ""), uid))
        db.commit(); flash(f"แบนลูกค้า {u['username']} แล้ว — เขาจะเข้าสู่ระบบไม่ได้")
    return redirect(url_for("admin.users", tab="ban"))

@admin_bp.route("/users/<int:uid>/unban", methods=["POST"])
@admin_required
def user_unban(uid):
    db = get_db(); db.execute("UPDATE users SET banned=0, ban_reason='', banned_at='' WHERE id=? AND is_admin=0", (uid,)); db.commit()
    flash("ปลดแบนแล้ว"); return redirect(url_for("admin.users", tab="ban"))

@admin_bp.route("/ban-reasons/add", methods=["POST"])
@admin_required
def ban_reason_add():
    r = request.form.get("reason", "").strip()[:100]; db = get_db()
    if not r: flash("กรุณาพิมพ์สาเหตุ", "warn")
    elif db.execute("SELECT 1 FROM ban_reasons WHERE reason=?", (r,)).fetchone(): flash("มีสาเหตุนี้อยู่แล้ว", "warn")
    else: db.execute("INSERT INTO ban_reasons(reason) VALUES(?)", (r,)); db.commit(); flash("เพิ่มสาเหตุการแบนแล้ว")
    return redirect(url_for("admin.users", tab="ban") + "#reasons")

@admin_bp.route("/ban-reasons/<int:rid>/delete", methods=["POST"])
@admin_required
def ban_reason_delete(rid):
    db = get_db(); db.execute("DELETE FROM ban_reasons WHERE id=?", (rid,)); db.commit()     # ลูกค้าที่ถูกแบนไปแล้วยังเห็นสาเหตุเดิม (เก็บเป็นข้อความ)
    flash("ลบสาเหตุออกจากรายการแล้ว"); return redirect(url_for("admin.users", tab="ban") + "#reasons")

# ---------- 3.2 อัปเดตการจัดส่ง: 1 รับ Order -> 2 กำลังจัดส่ง -> 3 จัดส่งสำเร็จ (ไปข้างหน้าทีละขั้น) ----------
@admin_bp.route("/orders/<int:oid>/ship", methods=["POST"])
@admin_required
def order_ship(oid):
    db = get_db(); back = redirect(url_for("admin.users", tab="ship", ship=request.form.get("flt", "active")))
    o = db.execute("SELECT o.*, u.email FROM orders o JOIN users u ON u.id=o.user_id WHERE o.id=?", (oid,)).fetchone()
    if not o or o["status"] != "paid": flash("อัปเดตจัดส่งได้เฉพาะคำสั่งซื้อที่อนุมัติการชำระเงินแล้ว", "warn"); return back
    note, step = request.form.get("note", "").strip()[:200], o["ship_step"]
    if request.form.get("action") == "advance":
        if step >= 3: flash("คำสั่งซื้อนี้จัดส่งสำเร็จแล้ว", "warn"); return back
        # UPDATE ... AND ship_step=ขั้นเดิม กันสองคนกดพร้อมกัน/กดซ้ำจนข้ามขั้น
        if not db.execute("UPDATE orders SET ship_step=? WHERE id=? AND ship_step=?", (step + 1, oid, step)).rowcount:
            flash("สถานะเพิ่งถูกเปลี่ยนไปแล้ว กรุณาตรวจสอบอีกครั้ง", "warn"); return back
        db.execute("INSERT INTO order_events(order_id,step,note) VALUES(?,?,?)", (oid, step + 1, note)); db.commit()
        if step + 1 in (2, 3) and (o["ship_email"] or o["email"]):
            send_mail(o["ship_email"] or o["email"], f"คำสั่งซื้อ #{o['user_order_no']} — {SHIP_STEPS[step + 1]}",
                      f"<h2>อัปเดตการจัดส่ง: {SHIP_STEPS[step + 1]}</h2><p>คำสั่งซื้อ #{o['user_order_no']}</p>" + (f"<p>{note}</p>" if note else ""))
        flash(f"อัปเดตคำสั่งซื้อ #{o['user_order_no']} เป็น \"{SHIP_STEPS[step + 1]}\" แล้ว (ลูกค้าเห็นทันที)")
    elif step < 1 or not note:
        flash("พิมพ์ข้อความก่อน (และต้องรับ Order แล้ว)", "warn")
    else:                                                      # เพิ่มหมายเหตุ เช่น เลขพัสดุ โดยไม่เปลี่ยนขั้นตอน
        db.execute("INSERT INTO order_events(order_id,step,note) VALUES(?,?,?)", (oid, step, note)); db.commit()
        flash("เพิ่มข้อความอัปเดตแล้ว (ลูกค้าเห็นทันที)")
    return back

# ---------- 2) ช่องทางชำระเงิน: ADMIN ตั้ง QR / รูปภาพให้ลูกค้าสแกนจ่ายที่หน้าชำระเงินขั้นตอน 2/2 ----------
@admin_bp.route("/payment", methods=["GET", "POST"])
@admin_required
def payment():
    db = get_db()
    if request.method == "POST":
        old = get_setting(db, "pay_qr"); new = old; f = request.files.get("qr")
        if f and f.filename:
            new, err = save_qr(f)                              # ตรวจนามสกุล + ไฟล์เป็นรูปจริง
            if err: flash("รูป QR ไม่ผ่าน: " + err, "warn"); return redirect(url_for("admin.payment"))
        elif request.form.get("remove_qr"): new = ""
        for k in ("pay_name", "pay_account", "pay_note"): set_setting(db, k, request.form.get(k, "").strip()[:200])
        set_setting(db, "pay_qr", new); db.commit()
        if new != old: delete_qr(old)                          # เปลี่ยน/ลบแล้ว -> ลบไฟล์เก่าทิ้ง
        flash("บันทึกช่องทางชำระเงินแล้ว"); return redirect(url_for("admin.payment"))
    return render_template("admin/payment.html", pay={k: get_setting(db, "pay_" + k) for k in ("qr", "name", "account", "note")})

@admin_bp.route("/users/<int:uid>")
@admin_required
def user_detail(uid):
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    data = [(o, order_lines(db, o["id"]))
            for o in db.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (uid,))]
    return render_template("admin/user_detail.html", u=u, data=data)

# ---------- คำสั่งซื้อ + ตรวจสอบการชำระเงิน ----------
# ลูกค้าอัปโหลดสลิป -> ออเดอร์เป็น pending -> ADMIN เปิดดูสลิป เทียบยอด แล้วกด "อนุมัติ" (paid) หรือ "ปฏิเสธ" (rejected + เหตุผล)
# ปฏิเสธ = คืนสต็อกสินค้าให้อัตโนมัติ / ตัดสินแล้วเปลี่ยนไม่ได้ (กันกดซ้ำ คืนสต็อกซ้ำ)
@admin_bp.route("/orders")
@admin_required
def orders():
    db = get_db()
    tab = request.args.get("status", "pending")
    if tab not in STATUS_TH: tab = "all"
    counts = {r["status"]: r["n"] for r in db.execute("SELECT status, COUNT(*) n FROM orders GROUP BY status")}
    counts["all"] = sum(counts.values())
    sql = "SELECT o.*, u.username FROM orders o JOIN users u ON u.id=o.user_id" + ("" if tab == "all" else " WHERE o.status=?")
    rows = db.execute(sql + " ORDER BY o.id DESC", () if tab == "all" else (tab,)).fetchall()
    return render_template("admin/orders.html", rows=rows, tab=tab, counts=counts)

@admin_bp.route("/orders/<int:oid>")
@admin_required
def order_detail(oid):
    db = get_db()
    o = db.execute("SELECT o.*, u.username FROM orders o JOIN users u ON u.id=o.user_id WHERE o.id=?", (oid,)).fetchone()
    if not o: flash("ไม่พบคำสั่งซื้อนี้"); return redirect(url_for("admin.orders"))
    return render_template("admin/order_detail.html", o=o, items=order_lines(db, oid))

def mail_result(o, ok, reason=""):
    """แจ้งลูกค้าทางอีเมลว่าอนุมัติหรือปฏิเสธ"""
    to = o["ship_email"] or o["email"]
    if not to: return
    if ok:
        send_mail(to, f"ยืนยันการชำระเงิน คำสั่งซื้อ #{o['user_order_no']}",
                  f"<h2>ร้านตรวจสอบการชำระเงินเรียบร้อยแล้ว</h2><p>คำสั่งซื้อ #{o['user_order_no']} ยอด {o['total']:,.2f} บาท — <b>อนุมัติแล้ว</b> "
                  f"ร้านจะจัดส่งสินค้าตามที่อยู่ที่ให้ไว้ และสามารถพิมพ์ใบเสร็จได้ที่หน้า \"คำสั่งซื้อของฉัน\"</p>")
    else:
        send_mail(to, f"คำสั่งซื้อ #{o['user_order_no']} ไม่ผ่านการตรวจสอบการชำระเงิน",
                  f"<h2>ขออภัย ร้านไม่สามารถยืนยันการชำระเงินได้</h2><p>คำสั่งซื้อ #{o['user_order_no']} ยอด {o['total']:,.2f} บาท</p>"
                  f"<p><b>เหตุผล:</b> {reason}</p><p>หากโอนเงินแล้ว กรุณาติดต่อร้านพร้อมหลักฐานการโอน</p>")

def decide(oid, new_status, reason=""):
    """เปลี่ยน pending -> paid / rejected เพียงครั้งเดียว (UPDATE ... WHERE status='pending' กันกดซ้ำพร้อมกัน)"""
    db = get_db()
    o = db.execute("SELECT o.*, u.email FROM orders o JOIN users u ON u.id=o.user_id WHERE o.id=?", (oid,)).fetchone()
    if not o: flash("ไม่พบคำสั่งซื้อนี้"); return redirect(url_for("admin.orders"))
    cur = db.execute("UPDATE orders SET status=?, reviewed_at=datetime('now'), reject_reason=? WHERE id=? AND status='pending'",
                     (new_status, reason, oid))
    if cur.rowcount == 0:
        flash(f"คำสั่งซื้อนี้ตัดสินไปแล้ว ({STATUS_TH.get(o['status'], o['status'])}) เปลี่ยนซ้ำไม่ได้", "warn")
        return redirect(url_for("admin.order_detail", oid=oid))
    if new_status == "rejected": restock_order(db, oid)        # ปฏิเสธ -> คืนสต็อก
    if new_status == "paid":                                   # อนุมัติ -> ขั้นตอนจัดส่งที่ 1 "รับ Order" อัตโนมัติ
        db.execute("UPDATE orders SET ship_step=1 WHERE id=?", (oid,))
        db.execute("INSERT INTO order_events(order_id,step,note) VALUES(?,1,?)", (oid, "ร้านตรวจสอบการชำระเงินแล้ว และรับ Order เข้าสู่ขั้นตอนจัดส่ง"))
    db.commit()
    mail_result(o, new_status == "paid", reason)
    flash(f"อนุมัติคำสั่งซื้อ #{o['user_order_no']} แล้ว" if new_status == "paid" else f"ปฏิเสธคำสั่งซื้อ #{o['user_order_no']} แล้ว (คืนสต็อกให้อัตโนมัติ)")
    return redirect(url_for("admin.orders"))

@admin_bp.route("/orders/<int:oid>/approve", methods=["POST"])
@admin_required
def order_approve(oid):
    return decide(oid, "paid")

@admin_bp.route("/orders/<int:oid>/reject", methods=["POST"])
@admin_required
def order_reject(oid):
    reason = request.form.get("reason", "").strip()[:300]
    if not reason:
        flash("กรุณาระบุเหตุผลที่ปฏิเสธ (ลูกค้าจะเห็นข้อความนี้)", "warn"); return redirect(url_for("admin.order_detail", oid=oid))
    return decide(oid, "rejected", reason)


# ---------- แบนเนอร์หน้าแรก (แก้ข้อความ รูป สี ปุ่ม ลำดับ เปิด/ปิด) ----------
def safe_link(v):
    """อนุญาตเฉพาะลิงก์ภายในเว็บ (/...) หรือ http(s) กัน javascript: ฯลฯ"""
    v = (v or "").strip()
    return v if v.startswith(("/", "http://", "https://", "#")) else ""

def crud_list(table, tpl):
    return render_template(tpl, rows=get_db().execute(f"SELECT * FROM {table} ORDER BY position, id").fetchall())

@admin_bp.route("/banners")
@admin_required
def banners(): return crud_list("banners", "admin/banners.html")

@admin_bp.route("/banners/new", methods=["GET", "POST"])
@admin_bp.route("/banners/<int:bid>/edit", methods=["GET", "POST"])
@admin_required
def banner_form(bid=None):
    db = get_db(); b = db.execute("SELECT * FROM banners WHERE id=?", (bid,)).fetchone() if bid else None
    if request.method == "POST":
        f = request.form
        img = "" if f.get("remove_image") else save_image(b["image"] if b else "")
        v = (f["title"], f["subtitle"], f["button_text"], safe_link(f["button_link"]), img,
             f.get("color") or "#0f1420", int(f.get("position") or 0), 1 if f.get("active") else 0)
        if b: db.execute("UPDATE banners SET title=?,subtitle=?,button_text=?,button_link=?,image=?,color=?,position=?,active=? WHERE id=?", v + (bid,))
        else: db.execute("INSERT INTO banners(title,subtitle,button_text,button_link,image,color,position,active) VALUES(?,?,?,?,?,?,?,?)", v)
        db.commit(); flash("บันทึกแบนเนอร์แล้ว"); return redirect(url_for("admin.banners"))
    return render_template("admin/banner_form.html", b=b)

@admin_bp.route("/banners/<int:bid>/delete", methods=["POST"])
@admin_required
def banner_delete(bid):
    db = get_db(); db.execute("DELETE FROM banners WHERE id=?", (bid,)); db.commit()
    flash("ลบแบนเนอร์แล้ว"); return redirect(url_for("admin.banners"))

# ---------- วิดเจ็ตหน้าแรก (text / image / quote / highlight) ----------
@admin_bp.route("/widgets")
@admin_required
def widgets(): return crud_list("widgets", "admin/widgets.html")

@admin_bp.route("/widgets/new", methods=["GET", "POST"])
@admin_bp.route("/widgets/<int:wid>/edit", methods=["GET", "POST"])
@admin_required
def widget_form(wid=None):
    db = get_db(); w = db.execute("SELECT * FROM widgets WHERE id=?", (wid,)).fetchone() if wid else None
    if request.method == "POST":
        f = request.form
        img = "" if f.get("remove_image") else save_image(w["image"] if w else "")
        v = (f["kind"], f["size"], f["title"], f["body"], img, f["link_text"], safe_link(f["link"]),
             int(f.get("position") or 0), 1 if f.get("active") else 0)
        if w: db.execute("UPDATE widgets SET kind=?,size=?,title=?,body=?,image=?,link_text=?,link=?,position=?,active=? WHERE id=?", v + (wid,))
        else: db.execute("INSERT INTO widgets(kind,size,title,body,image,link_text,link,position,active) VALUES(?,?,?,?,?,?,?,?,?)", v)
        db.commit(); flash("บันทึกวิดเจ็ตแล้ว"); return redirect(url_for("admin.widgets"))
    return render_template("admin/widget_form.html", w=w)

@admin_bp.route("/widgets/<int:wid>/delete", methods=["POST"])
@admin_required
def widget_delete(wid):
    db = get_db(); db.execute("DELETE FROM widgets WHERE id=?", (wid,)); db.commit()
    flash("ลบวิดเจ็ตแล้ว"); return redirect(url_for("admin.widgets"))

# ---------- คอมเมนต์ลูกค้า (แสดงล่างสุดหน้าแรก): ADMIN เพิ่ม / ลบได้ทุกอัน ----------
# เพิ่มได้ 2 แบบ: ใส่ "ชื่อที่แสดง" = ลงในนามลูกค้าคนนั้น / เว้นว่าง = ลงในนาม ADMIN (ขึ้นป้าย "ร้านค้า")
@admin_bp.route("/comments", methods=["GET", "POST"])
@admin_required
def comments():
    db = get_db()
    if request.method == "POST":
        body, author = request.form.get("body", "").strip(), request.form.get("author", "").strip()[:60]
        if not body: flash("กรุณาพิมพ์ข้อความคอมเมนต์")
        elif len(body) > 500: flash("คอมเมนต์ยาวเกินไป (ไม่เกิน 500 ตัวอักษร)")
        else:
            db.execute("INSERT INTO comments(user_id,body,author) VALUES(?,?,?)", (g.user["id"], body, author)); db.commit()
            flash("เพิ่มคอมเมนต์แล้ว (แสดงที่ล่างสุดหน้าแรก)")
        return redirect(url_for("admin.comments"))
    rows = db.execute("""SELECT c.*, u.username, u.full_name, u.is_admin FROM comments c
                         JOIN users u ON u.id=c.user_id ORDER BY c.id DESC LIMIT 300""").fetchall()
    return render_template("admin/comments.html", rows=rows)

@admin_bp.route("/comments/<int:cid>/delete", methods=["POST"])
@admin_required
def comment_delete(cid):
    db = get_db(); db.execute("DELETE FROM comments WHERE id=?", (cid,)); db.commit()
    flash("ลบคอมเมนต์แล้ว"); return redirect(url_for("admin.comments"))

# ---------- รายได้: วัน / เดือน / ปี + กราฟเปรียบเทียบช่วงก่อนหน้า (คำนวณใน reports.py) ----------
# เวลาใน DB เป็น UTC (CURRENT_TIMESTAMP) จึงบวก 7 ชั่วโมงให้เป็น "วันตามเวลาไทย" ก่อนเทียบวันที่
THAI_DAY = "date(o.created_at,'+7 hours')"

def thai_today():
    return (datetime.utcnow() + timedelta(hours=7)).date()

@admin_bp.route("/sales")
@admin_required
def sales():
    r = reports.period_report(get_db(), request.args.get("period", "day"), request.args, thai_today())
    return render_template("admin/sales.html", r=r, today=thai_today())
