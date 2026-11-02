# ============================================================
# mailer.py  —  ส่งอีเมลผ่าน Gmail SMTP (ทำงานเบื้องหลัง ไม่ทำให้เว็บช้า)
# ใช้งาน:  from mailer import send_mail ; send_mail(อีเมลผู้รับ, หัวข้อ, เนื้อหา HTML)
# ============================================================
import smtplib, threading
from email.mime.text import MIMEText
from flask import current_app

def _send(cfg, to, subject, html):
    if not cfg["SMTP_PASS"]:   # ยังไม่ตั้ง App Password -> พิมพ์ลงหน้าจอ cmd แทน (ใช้ทดสอบ)
        print(f"[MAIL-DEMO] ถึง {to} | {subject}\n(ตั้ง SMTP_PASS เพื่อส่งจริง)")
        return
    try:
        msg = MIMEText(html, "html", "utf-8")
        msg["Subject"], msg["From"], msg["To"] = subject, cfg["SMTP_USER"], to
        with smtplib.SMTP_SSL(cfg["SMTP_HOST"], cfg["SMTP_PORT"]) as s:
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
            s.sendmail(cfg["SMTP_USER"], [to], msg.as_string())
    except Exception as e:     # ส่งไม่สำเร็จต้องไม่ทำให้การสั่งซื้อพัง
        print("[MAIL-ERROR]", e)

def send_mail(to, subject, html):
    cfg = {k: current_app.config[k] for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS")}
    threading.Thread(target=_send, args=(cfg, to, subject, html), daemon=True).start()
