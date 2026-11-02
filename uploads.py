# ============================================================
# uploads.py  —  ตัวช่วยบันทึกไฟล์ที่ลูกค้าอัปโหลด: รูปโปรไฟล์ + สลิปโอนเงิน
# ใช้ใน shop.py   (from uploads import save_avatar, save_slip, delete_avatar)
# ตรวจ 3 อย่าง: นามสกุลอนุญาต / ไฟล์ไม่ว่าง / หัวไฟล์เป็นรูปจริง (ไม่ใช่แค่เปลี่ยนนามสกุล)
# ============================================================
import os, uuid
from flask import current_app

def _is_image(head):
    """ดู magic bytes ต้นไฟล์ว่าเป็น PNG / JPEG / WEBP / GIF จริงหรือไม่"""
    return (head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff")
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP") or head[:6] in (b"GIF87a", b"GIF89a"))

def _save(f, folder, allowed, prefix=""):
    """คืน (ชื่อไฟล์ที่บันทึก, None) ถ้าสำเร็จ / (None, ข้อความ error) ถ้าไม่ผ่าน"""
    if not f or not f.filename:
        return None, "ยังไม่ได้เลือกไฟล์"
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in allowed:
        return None, "ไฟล์ต้องเป็นรูป " + ", ".join(sorted(allowed)).upper() + " เท่านั้น"
    head = f.stream.read(16); f.stream.seek(0)
    if not head or not _is_image(head):
        return None, "ไฟล์ที่เลือกไม่ใช่รูปภาพที่ถูกต้อง"
    os.makedirs(folder, exist_ok=True)
    name = f"{prefix}{uuid.uuid4().hex}.{ext}"
    f.save(os.path.join(folder, name))
    return name, None

def save_avatar(f):
    """รูปโปรไฟล์ -> static/uploads/avatar_xxx.png ; คืน (พาธสำหรับใช้ใน <img>, error)"""
    cfg = current_app.config
    name, err = _save(f, cfg["UPLOAD_FOLDER"], cfg["ALLOWED_EXT"], "avatar_")
    return ("/static/uploads/" + name if name else None), err

def delete_avatar(path):
    """ลบรูปโปรไฟล์เก่าออกจากดิสก์ (ลบเฉพาะไฟล์ avatar_ ที่ระบบสร้าง ไม่แตะรูปสินค้า/แบนเนอร์)"""
    if path and path.startswith("/static/uploads/avatar_"):
        p = os.path.join(current_app.config["UPLOAD_FOLDER"], os.path.basename(path))
        if os.path.isfile(p):
            os.remove(p)

def save_slip(f):
    """สลิปโอนเงิน -> slips/slip_xxx.jpg (นอก static) ; คืน (ชื่อไฟล์, error)"""
    cfg = current_app.config
    return _save(f, cfg["SLIP_FOLDER"], cfg["SLIP_EXT"], "slip_")

def save_qr(f):
    """รูป QR / รูปสำหรับให้ลูกค้าสแกนจ่ายเงิน -> static/uploads/qr_xxx.png (เปิดให้ลูกค้าเห็นได้ตามวัตถุประสงค์) ; คืน (พาธ, error)"""
    cfg = current_app.config
    name, err = _save(f, cfg["UPLOAD_FOLDER"], cfg["ALLOWED_EXT"], "qr_")
    return ("/static/uploads/" + name if name else None), err

def delete_qr(path):
    """ลบไฟล์ QR เก่า (เฉพาะไฟล์ qr_ ที่ระบบสร้าง)"""
    if path and path.startswith("/static/uploads/qr_"):
        p = os.path.join(current_app.config["UPLOAD_FOLDER"], os.path.basename(path))
        if os.path.isfile(p):
            os.remove(p)
