# ============================================================
# shop.py  —  หน้าฝั่งลูกค้า: หน้าแรก, สินค้า (หลายสี), ค้นหา+คำใบ้, ตะกร้า, ชำระเงิน, คำสั่งซื้อ, โปรไฟล์
# ถูกเชื่อมเข้าแอปใน app.py ด้วย:  app.register_blueprint(shop_bp)
# ============================================================
import random, re
from flask import (current_app, Blueprint, render_template, request, redirect, url_for, session, flash, g, jsonify,
                   abort, send_from_directory)
from database import get_db, order_lines, PRODUCT_SQL, get_setting
from auth import login_required, check_contact
from mailer import send_mail
from uploads import save_avatar, delete_avatar, save_slip
import os

shop_bp = Blueprint("shop", __name__)

@shop_bp.route("/")
def home():
    db = get_db()
    items = db.execute(PRODUCT_SQL + " ORDER BY p.id DESC LIMIT 4").fetchall()
    # หมวดหมู่ (จากตาราง categories) + จำนวนสินค้า + รูปตัวแทน ใช้ในส่วน Our Collections
    cats = db.execute("""SELECT c.name category, COUNT(p.id) n,
        COALESCE(NULLIF(MAX(p.image),''), (SELECT pc.image FROM product_colors pc JOIN products pp ON pp.id=pc.product_id
                                           WHERE pp.category=c.name AND pc.image!='' LIMIT 1), '') image
        FROM categories c JOIN products p ON p.category=c.name GROUP BY c.id ORDER BY c.position, c.name""").fetchall()
    banners = db.execute("SELECT * FROM banners WHERE active=1 ORDER BY position,id").fetchall()
    widgets = db.execute("SELECT * FROM widgets WHERE active=1 ORDER BY position,id").fetchall()
    comments = db.execute("""SELECT c.*, u.full_name, u.username, u.avatar, u.is_admin FROM comments c
        JOIN users u ON u.id=c.user_id ORDER BY c.id DESC LIMIT 20""").fetchall()
    return render_template("home.html", items=items, cats=cats, banners=banners, widgets=widgets, comments=comments)

# ---------- คอมเมนต์ลูกค้า (ล่างสุดของหน้าแรก): ลูกค้าที่ล็อกอินเขียนได้ / เจ้าของลบของตัวเองได้ / ADMIN ลบได้ทุกอัน ----------
COMMENT_MAX = 500

@shop_bp.route("/comments/add", methods=["POST"])
@login_required
def comment_add():
    body = request.form.get("body", "").strip()
    db = get_db()
    if not body:
        flash("กรุณาพิมพ์ข้อความก่อนส่งคอมเมนต์", "warn")
    elif len(body) > COMMENT_MAX:
        flash(f"คอมเมนต์ยาวเกินไป (ไม่เกิน {COMMENT_MAX} ตัวอักษร)", "warn")
    elif db.execute("SELECT 1 FROM comments WHERE user_id=? AND created_at > datetime('now','-30 seconds')", (g.user["id"],)).fetchone():
        flash("ส่งคอมเมนต์ถี่เกินไป กรุณารอสักครู่แล้วลองใหม่", "warn")      # กันกดส่งรัว ๆ
    else:
        db.execute("INSERT INTO comments(user_id,body) VALUES(?,?)", (g.user["id"], body)); db.commit()
        flash("ขอบคุณสำหรับคอมเมนต์")
    return redirect(url_for("shop.home") + "#comments")

@shop_bp.route("/comments/<int:cid>/delete", methods=["POST"])
@login_required
def comment_delete(cid):
    db = get_db(); c = db.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
    if c and (c["user_id"] == g.user["id"] or g.user["is_admin"]):
        db.execute("DELETE FROM comments WHERE id=?", (cid,)); db.commit(); flash("ลบคอมเมนต์แล้ว")
    return redirect(url_for("shop.home") + "#comments")

# ---------- รายการสินค้า + ค้นหา + กรอง (/products?q=...&cat=...&brand=...) ----------
@shop_bp.route("/products")
def products():
    q, brand, cat = request.args.get("q", "").strip(), request.args.get("brand", ""), request.args.get("cat", "")
    pmin, pmax = request.args.get("min", type=float), request.args.get("max", type=float)
    sql, args = PRODUCT_SQL + " WHERE 1=1", []
    if q:     # ค้นจาก ชื่อ / แบรนด์ / สี / หมวด / สีของตัวเลือกสี
        sql += " AND (p.name LIKE ? OR p.brand LIKE ? OR p.color LIKE ? OR p.category LIKE ? OR p.id IN (SELECT product_id FROM product_colors WHERE color LIKE ?))"
        args += [f"%{q}%"] * 5
    if cat:   sql += " AND p.category=?"; args.append(cat)
    if brand: sql += " AND p.brand=?"; args.append(brand)
    rate = 1 + current_app.config["VAT_RATE"]            # ลูกค้าเห็นราคารวม VAT -> แปลงกลับเป็นราคาก่อน VAT
    if pmin is not None: sql += " AND p.price>=?"; args.append(pmin / rate)
    if pmax is not None: sql += " AND p.price<=?"; args.append(pmax / rate)
    db = get_db()
    items = db.execute(sql + " ORDER BY p.id DESC", args).fetchall()
    brands = [r["brand"] for r in db.execute("SELECT DISTINCT brand FROM products WHERE brand!='' ORDER BY brand")]
    cats = [r["name"] for r in db.execute("SELECT name FROM categories ORDER BY position, name")]
    return render_template("products.html", items=items, brands=brands, cats=cats, q=q, brand=brand, cat=cat)

@shop_bp.route("/product/<int:pid>")
def product(pid):
    db = get_db(); p = db.execute(PRODUCT_SQL + " WHERE p.id=?", (pid,)).fetchone()
    if not p: return redirect(url_for("shop.products"))
    colors = db.execute("SELECT * FROM product_colors WHERE product_id=? ORDER BY id", (pid,)).fetchall()
    default_cid = next((c["id"] for c in colors if c["stock"] > 0), None)   # สีแรกที่ยังมีของ
    return render_template("product.html", p=p, colors=colors, default_cid=default_cid)

def shown_price(price):
    """ราคาที่ลูกค้าเห็น = ราคาก่อน VAT + VAT (แสดงเป็นราคาเดียว ไม่แจกแจง VAT) เช่น 14900 -> '฿15,943'"""
    v = round(price * (1 + current_app.config["VAT_RATE"]), 2)
    return f"฿{v:,.0f}" if v == int(v) else f"฿{v:,.2f}"

# ---------- คำใบ้ตอนพิมพ์ค้นหา: JS (static/app.js) เรียก /api/suggest?q=ตัวอักษรที่พิมพ์ ----------
@shop_bp.route("/api/suggest")
def suggest():
    q = request.args.get("q", "").strip()[:40].replace("%", "").replace("_", "")
    if not q: return jsonify([])
    like, pre, db, out = f"%{q}%", f"{q}%", get_db(), []
    for r in db.execute("""SELECT id,name,price FROM products WHERE name LIKE ? OR brand LIKE ? OR category LIKE ?
            OR id IN (SELECT product_id FROM product_colors WHERE color LIKE ?)
            ORDER BY (name LIKE ?) DESC, (brand LIKE ?) DESC, name LIMIT 6""", (like, like, like, like, pre, pre)):
        out.append({"type": "สินค้า", "label": r["name"], "sub": shown_price(r["price"]), "url": url_for("shop.product", pid=r["id"])})
    for r in db.execute("SELECT DISTINCT brand FROM products WHERE brand!='' AND brand LIKE ? LIMIT 3", (like,)):
        out.append({"type": "แบรนด์", "label": r["brand"], "sub": "", "url": url_for("shop.products", brand=r["brand"])})
    for r in db.execute("SELECT name FROM categories WHERE name LIKE ? LIMIT 3", (like,)):
        out.append({"type": "หมวดหมู่", "label": r["name"], "sub": "", "url": url_for("shop.products", cat=r["name"])})
    return jsonify(out)

# ---------- ตะกร้า: session["cart"] = { "คีย์": จำนวน }  คีย์ = "id สินค้า-id สี" (สินค้าไม่มีสีใช้ "id สินค้า" เฉย ๆ) ----------
def cart_items():
    """คืน (รายการ, ยอดรวม) แต่ละรายการเป็น dict: key, p, color, image, stock, qty, price, sub"""
    db, rows, total = get_db(), [], 0
    for key, qty in list(session.get("cart", {}).items()):
        try: pid, _, cid = str(key).partition("-"); pid, cid = int(pid), int(cid or 0)
        except ValueError: continue
        p = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if not p: continue
        has_colors = db.execute("SELECT COUNT(*) n FROM product_colors WHERE product_id=?", (pid,)).fetchone()["n"] > 0
        col = db.execute("SELECT * FROM product_colors WHERE id=? AND product_id=?", (cid, pid)).fetchone() if cid else None
        if (cid and not col) or (has_colors and not col): continue         # สีถูกลบไปแล้ว -> ข้าม
        it = dict(key=key, p=p, color=col["color"] if col else (p["color"] or ""),
                  image=(col["image"] if col and col["image"] else p["image"]),
                  stock=col["stock"] if col else p["stock"], qty=qty, price=p["price"], sub=p["price"] * qty,
                  cid=col["id"] if col else 0)
        rows.append(it); total += it["sub"]
    return rows, total

def vat_split(subtotal):
    """รับยอดก่อน VAT -> คืน (VAT, ยอดรวม VAT) ปัดเป็นสตางค์ คิดจากยอดรวมทั้งตะกร้า (ไม่ปัดทีละชิ้น)"""
    vat = round(subtotal * current_app.config["VAT_RATE"], 2)
    return vat, round(subtotal + vat, 2)

def label(it):   # ชื่อสินค้า + สี สำหรับข้อความแจ้งเตือน
    return it["p"]["name"] + (f" ({it['color']})" if it["color"] else "")

@shop_bp.route("/cart")
def cart():
    rows, total = cart_items()
    vat, grand = vat_split(total)
    return render_template("cart.html", rows=rows, total=total, vat=vat, grand=grand)

@shop_bp.route("/cart/add/<int:pid>", methods=["POST"])
def cart_add(pid):
    """เพิ่มทีละ 1 ชิ้น: สินค้าหลายสีต้องเลือกสีก่อน และห้ามเกินสต็อกของสีนั้น"""
    db, back = get_db(), (request.referrer or url_for("shop.cart"))
    p = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not p: flash("ไม่พบสินค้านี้", "warn"); return redirect(back)
    cid = request.form.get("cid", type=int, default=0)
    ncol = db.execute("SELECT COUNT(*) n FROM product_colors WHERE product_id=?", (pid,)).fetchone()["n"]
    col = None
    if ncol:
        col = db.execute("SELECT * FROM product_colors WHERE id=? AND product_id=?", (cid, pid)).fetchone() if cid else None
        if not col: flash("กรุณาเลือกสีของสินค้าก่อนใส่ตะกร้า", "warn"); return redirect(url_for("shop.product", pid=pid))
    key = f"{pid}-{col['id']}" if col else str(pid)
    stock, name = (col["stock"] if col else p["stock"]), p["name"] + (f" ({col['color']})" if col else "")
    c = session.get("cart", {}); have = c.get(key, 0)
    if stock <= 0:
        flash(f"ขออภัย {name} หมดสต็อกแล้ว", "warn")
    elif have + 1 > stock:
        flash(f"เพิ่มไม่ได้: {name} เหลือในสต็อกเพียง {stock} ชิ้น (คุณมีในตะกร้าแล้ว {have} ชิ้น)", "warn")
    else:
        c[key] = have + 1; session["cart"] = c; flash("เพิ่มลงตะกร้าแล้ว")
    return redirect(back)

@shop_bp.route("/cart/update/<key>", methods=["POST"])
def cart_update(key):
    c = session.get("cart", {}); qty = request.form.get("qty", type=int, default=1)
    it = next((r for r in cart_items()[0] if r["key"] == key), None)
    if qty <= 0: c.pop(key, None)
    elif it and qty > it["stock"]:
        flash(f"ใส่ไม่ได้: {label(it)} เหลือในสต็อกเพียง {it['stock']} ชิ้น", "warn"); return redirect(url_for("shop.cart"))
    elif it: c[key] = qty
    session["cart"] = c; return redirect(url_for("shop.cart"))

@shop_bp.route("/cart/remove/<key>", methods=["POST"])
def cart_remove(key):      # ปุ่ม "ยกเลิกสินค้า"
    c = session.get("cart", {}); c.pop(key, None); session["cart"] = c
    flash("ยกเลิกสินค้านี้ออกจากตะกร้าแล้ว"); return redirect(url_for("shop.cart"))

@shop_bp.route("/cart/clear", methods=["POST"])
def cart_clear():
    session.pop("cart", None); flash("ล้างตะกร้าแล้ว"); return redirect(url_for("shop.cart"))

# ---------- ชำระเงิน 3 ขั้นตอน: /checkout (ตรวจสอบ) -> /checkout/pay (QR) -> บันทึกออเดอร์ + ส่งอีเมล ----------
def fake_qr_svg(seed):
    """สร้าง QR จำลอง (ไม่ใช่ QR จริง ใช้เพื่อโปรเจกต์เรียนรู้)"""
    r, n, cells = random.Random(seed), 25, ""
    for y in range(n):
        for x in range(n):
            finder = (x < 7 and y < 7) or (x > 17 and y < 7) or (x < 7 and y > 17)
            if (finder and (x % 6 in (0,) or y % 6 in (0,) or (2 <= x % 18 <= 4 and 2 <= y % 18 <= 4))) or (not finder and r.random() < .5):
                cells += f'<rect x="{x}" y="{y}" width="1" height="1"/>'
    return f'<svg viewBox="-1 -1 27 27" width="220" height="220" fill="#0f1420">{cells}</svg>'

def cart_sig():
    return repr(sorted(session.get("cart", {}).items()))

def profile_complete():
    return all(g.user[k] for k in ("full_name", "phone", "address"))

@shop_bp.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    rows, total = cart_items()
    if not rows: flash("ตะกร้าว่าง"); return redirect(url_for("shop.products"))
    for it in rows:
        if it["qty"] > it["stock"]:
            flash(f"{label(it)} เหลือในสต็อกเพียง {it['stock']} ชิ้น กรุณาลดจำนวนในตะกร้า", "warn"); return redirect(url_for("shop.cart"))
    ok = profile_complete()
    if request.method == "POST":
        if not ok: flash("กรุณากรอกชื่อ เบอร์โทร และที่อยู่ให้ครบก่อน", "warn")
        elif not request.form.get("agree"): flash("กรุณาติ๊กยืนยันว่าข้อมูลถูกต้อง", "warn")
        else:
            session["confirmed"] = cart_sig(); return redirect(url_for("shop.pay"))
    vat, grand = vat_split(total)
    return render_template("checkout.html", rows=rows, total=total, vat=vat, grand=grand, ok=ok)

@shop_bp.route("/checkout/pay", methods=["GET", "POST"])
@login_required
def pay():
    rows, total = cart_items()
    if not rows or session.get("confirmed") != cart_sig() or not profile_complete():
        return redirect(url_for("shop.checkout"))
    vat, grand = vat_split(total)
    if request.method == "POST":
        for it in rows:
            if it["qty"] > it["stock"]:
                flash(f"{label(it)} เหลือไม่พอ (เหลือ {it['stock']} ชิ้น)", "warn"); return redirect(url_for("shop.cart"))
        # ---- ต้องแนบสลิปโอนเงินก่อนเสมอ (ปุ่มฝั่งหน้าเว็บกันไว้ชั้นแรก / ตรงนี้กันซ้ำที่ฝั่งเซิร์ฟเวอร์) ----
        up = request.files.get("slip")
        if not up or not up.filename:
            flash("กรุณาแนบสลิปโอนเงินก่อน จึงจะดำเนินการต่อได้", "warn"); return redirect(url_for("shop.pay"))
        slip, err = save_slip(up)
        if err:
            flash("สลิปไม่ถูกต้อง: " + err, "warn"); return redirect(url_for("shop.pay"))
        db, u = get_db(), g.user
        try:
            oid = db.execute("""INSERT INTO orders(user_id,total,subtotal,vat,vat_rate,ship_name,ship_phone,ship_email,ship_address,slip,status,user_order_no)
                             VALUES(?,?,?,?,?,?,?,?,?,?,'pending',(SELECT COALESCE(MAX(user_order_no),0)+1 FROM orders WHERE user_id=?))""",
                             (u["id"], grand, total, vat, current_app.config["VAT_RATE"], u["full_name"], u["phone"], u["email"], u["address"], slip, u["id"])).lastrowid
            no = db.execute("SELECT user_order_no FROM orders WHERE id=?", (oid,)).fetchone()[0]   # เลขของลูกค้าคนนี้ ใช้แสดงและส่งอีเมล
            for it in rows:
                db.execute("INSERT INTO order_items(order_id,product_id,name,price,qty,image,color) VALUES(?,?,?,?,?,?,?)",
                           (oid, it["p"]["id"], it["p"]["name"], it["price"], it["qty"], it["image"], it["color"]))
                if it["cid"]: db.execute("UPDATE product_colors SET stock=MAX(stock-?,0) WHERE id=?", (it["qty"], it["cid"]))   # ลดสต็อกของสีนั้น
                else:         db.execute("UPDATE products SET stock=MAX(stock-?,0) WHERE id=?", (it["qty"], it["p"]["id"]))
            db.commit()
        except Exception:                      # บันทึกออเดอร์ไม่สำเร็จ -> ลบสลิปที่เพิ่งเก็บทิ้ง ไม่ให้ค้างเป็นไฟล์ขยะ
            db.rollback()
            try: os.remove(os.path.join(current_app.config["SLIP_FOLDER"], slip))
            except OSError: pass
            raise
        session.pop("cart", None); session.pop("confirmed", None)
        lines = "".join(f"<tr><td>{label(it)}</td><td>{it['qty']}</td><td>{it['sub']:,.2f} บาท</td></tr>" for it in rows)
        body = (f"<h2>ขอบคุณที่ซื้อสินค้ากับ Aor-Au Smart Watch</h2><p>เลขที่คำสั่งซื้อ #{no} — ได้รับสลิปแล้ว รอร้านตรวจสอบการชำระเงิน (จะแจ้งผลทางอีเมลอีกครั้ง)</p>"
                f"<table border=1 cellpadding=6><tr><th>สินค้า</th><th>จำนวน</th><th>ราคา</th></tr>{lines}</table>"
                f"<h3>ยอดชำระทั้งสิ้น {grand:,.2f} บาท (แนบสลิปแล้ว · รอตรวจสอบ)</h3><p><b>จัดส่งถึง:</b> {u['full_name']} โทร {u['phone']}<br>{u['address']}</p>")
        send_mail(u["email"], f"ได้รับคำสั่งซื้อ #{no} — รอตรวจสอบการชำระเงิน", body)
        send_mail(current_app.config["ADMIN_EMAIL"], f"[ADMIN] ออเดอร์ใหม่ #{no} ของ {u['username']} (รหัสระบบ {oid}) — รอตรวจสลิป", body)
        return redirect(url_for("shop.order_done", oid=oid))
    db = get_db()                                          # QR / ข้อมูลบัญชีที่ ADMIN ตั้งไว้ที่หน้า "ช่องทางชำระเงิน"
    pay_info = dict(qr=get_setting(db, "pay_qr"), name=get_setting(db, "pay_name"),
                    account=get_setting(db, "pay_account"), note=get_setting(db, "pay_note"))
    return render_template("pay.html", total=total, vat=vat, grand=grand, qr=fake_qr_svg(grand), pay=pay_info)

def own_order(oid):
    """คืนออเดอร์ถ้าเป็นของผู้ล็อกอิน (หรือผู้ล็อกอินเป็น ADMIN) ไม่งั้น 404 — กันดูใบเสร็จ/สลิปของคนอื่น"""
    o = get_db().execute("SELECT o.*, u.username FROM orders o JOIN users u ON u.id=o.user_id WHERE o.id=?", (oid,)).fetchone()
    if not o or (o["user_id"] != g.user["id"] and not g.user["is_admin"]): abort(404)
    return o

@shop_bp.route("/order/<int:oid>/done")
@login_required
def order_done(oid):
    return render_template("order_done.html", o=own_order(oid))

# ---------- ใบเสร็จ (หน้าสำหรับพิมพ์ / บันทึกเป็น PDF จากเบราว์เซอร์) ----------
@shop_bp.route("/order/<int:oid>/receipt")
@login_required
def receipt(oid):
    o = own_order(oid)
    if o["status"] != "paid" and not g.user["is_admin"]:       # ยังไม่ผ่านการตรวจสอบ = ยังไม่ออกใบเสร็จ
        flash("ใบเสร็จจะออกให้หลังร้านตรวจสอบและอนุมัติการชำระเงินแล้ว", "warn"); return redirect(url_for("shop.orders"))
    return render_template("receipt.html", o=o, items=order_lines(get_db(), oid))

# ---------- ดูสลิป: เปิดได้เฉพาะเจ้าของออเดอร์และ ADMIN ----------
@shop_bp.route("/order/<int:oid>/slip")
@login_required
def order_slip(oid):
    o = own_order(oid)
    if not o["slip"]: abort(404)
    resp = send_from_directory(current_app.config["SLIP_FOLDER"], o["slip"])
    resp.headers["Cache-Control"] = "private, max-age=0"; resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp

def tracking_events(db, oid):
    """บันทึกอัปเดตจัดส่งของออเดอร์ (ใหม่สุดอยู่บน)"""
    return db.execute("SELECT * FROM order_events WHERE order_id=? ORDER BY id DESC", (oid,)).fetchall()

@shop_bp.route("/orders")
@login_required
def orders():
    db = get_db()
    data = [(o, order_lines(db, o["id"])) for o in db.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (g.user["id"],))]
    ev = {o["id"]: tracking_events(db, o["id"]) for o, _ in data if o["status"] == "paid"}
    return render_template("orders.html", data=data, ev=ev)

# ---------- ติดตามการจัดส่งแบบ Real time: หน้า "คำสั่งซื้อของฉัน" ถาม /api/tracking ทุก 5 วินาที ----------
# ถ้ารหัส (ขั้นตอน:จำนวนอัปเดต) ของออเดอร์ไหนเปลี่ยน JS จะดึงส่วนแสดงผลใหม่ของออเดอร์นั้นมาแทนที่ทันที (ไม่ต้องรีเฟรชหน้า)
def no_store(resp):
    resp.headers["Cache-Control"] = "no-store"; return resp

@shop_bp.route("/api/tracking")
@login_required
def api_tracking():
    db, out = get_db(), {}
    for o in db.execute("SELECT id, ship_step FROM orders WHERE user_id=? AND status='paid'", (g.user["id"],)):
        n = db.execute("SELECT COUNT(*) FROM order_events WHERE order_id=?", (o["id"],)).fetchone()[0]
        out[o["id"]] = f"{o['ship_step']}:{n}"
    return no_store(jsonify(out))

@shop_bp.route("/order/<int:oid>/tracking")
@login_required
def order_tracking(oid):
    o = own_order(oid)
    return no_store(current_app.make_response(render_template("_tracking.html", o=o, events=tracking_events(get_db(), oid))))

# ---------- ข้อมูลของฉัน (ใช้ร่วมกันทั้งลูกค้าและ ADMIN): ดูได้ทันที / แก้ไขต้องกดปุ่ม "แก้ไขข้อมูล" (?edit=1) ----------
# แก้ได้: รูปโปรไฟล์, ชื่อ-นามสกุล, เบอร์โทร, ที่อยู่ (ลูกค้าแก้อีเมลได้ด้วย)
# ADMIN: อีเมลถูกกำหนดจาก config.py (ระบบซิงก์ทุกครั้งที่เปิดโปรแกรม) จึงไม่ให้แก้ตรงนี้ และเบอร์/ที่อยู่ไม่บังคับ
@shop_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    nxt = request.values.get("next", "")
    nxt = nxt if nxt.startswith("/") and not nxt.startswith("//") else ""
    u = g.user; is_admin = bool(u["is_admin"])
    if request.method == "POST":
        f = request.form; db = get_db()
        name, phone, addr = f.get("full_name", "").strip(), f.get("phone", "").strip(), f.get("address", "").strip()
        email = u["email"] if is_admin else f.get("email", "").strip().lower()
        if is_admin:
            err = "กรุณากรอกชื่อ" if not name else ("เบอร์โทรต้องเป็นตัวเลข 9-10 หลัก" if phone and not re.fullmatch(r"[0-9]{9,10}", phone) else None)
        else:
            err = check_contact(name, email, phone)
        new_avatar = None
        if not err and request.files.get("avatar") and request.files["avatar"].filename:
            new_avatar, err = save_avatar(request.files["avatar"])      # รูปไม่ผ่าน = ไม่บันทึกอะไรเลย
        if err:
            flash(err, "warn"); return redirect(url_for("shop.profile", edit=1, next=nxt))
        avatar = new_avatar if new_avatar else ("" if f.get("remove_avatar") else u["avatar"])
        try:
            db.execute("UPDATE users SET full_name=?,phone=?,address=?,email=?,avatar=? WHERE id=?", (name, phone, addr, email, avatar, u["id"]))
            db.commit()
        except Exception:
            if new_avatar: delete_avatar(new_avatar)
            flash("อีเมลนี้ถูกใช้แล้ว", "warn"); return redirect(url_for("shop.profile", edit=1, next=nxt))
        if avatar != u["avatar"]: delete_avatar(u["avatar"])             # เปลี่ยน/ลบรูปแล้ว -> ลบไฟล์เก่าทิ้ง
        flash("บันทึกข้อมูลแล้ว")
        return redirect(nxt or url_for("shop.profile"))
    st = get_db().execute("SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN status='paid' THEN total END),0) s FROM orders WHERE user_id=?", (u["id"],)).fetchone()
    return render_template("profile.html", edit=bool(request.args.get("edit")), next=nxt, st=st)
