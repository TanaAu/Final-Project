# ============================================================
# reports.py  —  รายงานยอดขาย (วัน / เดือน / ปี) + กราฟแท่ง SVG (ไม่ใช้ไลบรารีกราฟภายนอก)
# ใช้ใน admin.py:  from reports import period_report, overview_report
# นับเฉพาะออเดอร์ที่ ADMIN "อนุมัติแล้ว" (status='paid') และใช้วันที่ตามเวลาไทย (UTC+7)
# ============================================================
import calendar, math, html
from datetime import date, timedelta
from markupsafe import Markup

L = "datetime(o.created_at,'+7 hours')"                       # เวลาไทยของออเดอร์
M_SHORT = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
M_FULL = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
CUR, PREV = "#2f4bff", "#b9c1da"                              # สีแท่ง: ช่วงที่เลือก / ช่วงก่อนหน้า

def agg(db, fmt, val):
    """สรุปยอดของช่วงเวลา: fmt = รูปแบบ strftime ของเวลาไทย เช่น '%Y-%m' / val = ค่าที่ต้องการ เช่น '2026-10'"""
    r = db.execute(f"""SELECT COUNT(*) n, COALESCE(SUM(o.total),0) rev, COALESCE(SUM(o.subtotal),0) ex, COALESCE(SUM(o.vat),0) vat
        FROM orders o WHERE o.status='paid' AND strftime('{fmt}',{L})=?""", (val,)).fetchone()
    u = db.execute(f"""SELECT COALESCE(SUM(oi.qty),0) FROM order_items oi JOIN orders o ON o.id=oi.order_id
        WHERE o.status='paid' AND strftime('{fmt}',{L})=?""", (val,)).fetchone()[0]
    return dict(n=r["n"], rev=r["rev"], ex=r["ex"], vat=r["vat"], units=u, avg=(r["rev"] / r["n"] if r["n"] else 0))

def pct(cur, prev):
    """% เปลี่ยนแปลงเทียบช่วงก่อน (None = ช่วงก่อนไม่มียอด เทียบไม่ได้)"""
    return None if not prev else round((cur - prev) / prev * 100, 1)

def series(db, fmt, val, bucket, size, first):
    """ยอดขายแยกเป็นช่อง (ชั่วโมง/วัน/เดือน) คืนลิสต์ความยาว size"""
    out = [0.0] * size
    for r in db.execute(f"""SELECT CAST(strftime('{bucket}',{L}) AS INTEGER) b, SUM(o.total) rev FROM orders o
        WHERE o.status='paid' AND strftime('{fmt}',{L})=? GROUP BY b""", (val,)):
        i = r["b"] - first
        if 0 <= i < size: out[i] = r["rev"]
    return out

# ---------- กราฟแท่ง SVG (หลายชุดข้อมูลวางเทียบกัน) ----------
def _nice(v):
    if v <= 0: return 1
    e = 10 ** math.floor(math.log10(v))
    return next(m * e for m in (1, 2, 2.5, 5, 10) if v <= m * e)

def _ax(v):
    return f"{v / 1e6:g}M" if v >= 1e6 else (f"{v / 1e3:g}k" if v >= 1e3 else f"{v:g}")

def bar_svg(labels, sers, title="", every=1, w=760, h=300):
    """sers = [(ชื่อชุด, [ค่า...], สี), ...] — ใส่ <title> ในแต่ละแท่งให้เอาเมาส์ชี้ดูยอดได้"""
    pl, pr, pt, pb = 52, 10, 12, 34
    cw, ch, n, k = w - pl - pr, h - pt - pb, len(labels), len(sers)
    ymax = _nice(max((max(v) for _, v, _ in sers), default=0)); gw = cw / n; bw = min(22, gw * .8 / k)
    e = html.escape
    p = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{e(title)}" class="chart">']
    for i in range(5):
        y = pt + ch - ch * i / 4
        p.append(f'<line x1="{pl}" x2="{w - pr}" y1="{y:.1f}" y2="{y:.1f}" class="gl"/><text x="{pl - 6}" y="{y + 4:.1f}" text-anchor="end" class="ax">{_ax(ymax * i / 4)}</text>')
    for gi in range(n):
        gx = pl + gw * gi + gw / 2
        for si, (name, vals, color) in enumerate(sers):
            v = vals[gi]; bh = ch * v / ymax; x = gx - bw * k / 2 + si * bw
            p.append(f'<rect x="{x:.1f}" y="{pt + ch - bh:.1f}" width="{max(bw - 1, 1):.1f}" height="{bh:.1f}" rx="2" fill="{color}"><title>{e(name)} · {e(labels[gi])}: ฿{v:,.2f}</title></rect>')
        if gi % every == 0:
            p.append(f'<text x="{gx:.1f}" y="{h - 12}" text-anchor="middle" class="ax">{e(labels[gi])}</text>')
    p.append("</svg>")
    return Markup("".join(p))

# ---------- รายงานตามช่วงเวลา: period = day | month | year ----------
def period_report(db, period, args, today):
    if period == "month":
        try: y, m = map(int, args.get("month", "").split("-")); d0 = date(y, m, 1)
        except ValueError: d0 = today.replace(day=1)
        pv = (d0 - timedelta(days=1)).replace(day=1); nx = (d0 + timedelta(days=32)).replace(day=1)
        fmt, cur, prv = "%Y-%m", d0.strftime("%Y-%m"), pv.strftime("%Y-%m")
        n = max(calendar.monthrange(d0.year, d0.month)[1], calendar.monthrange(pv.year, pv.month)[1])
        labels, first, bucket, every = [str(i) for i in range(1, n + 1)], 1, "%d", 2
        title, ptitle = f"{M_FULL[d0.month - 1]} {d0.year + 543}", f"{M_FULL[pv.month - 1]} {pv.year + 543}"
        pa, na = {"month": pv.strftime("%Y-%m")}, ({"month": nx.strftime("%Y-%m")} if nx <= today else None)
        unit, picker = "รายวันในเดือน", cur
    elif period == "year":
        try: y = int(args.get("year", ""))
        except ValueError: y = today.year
        y = min(max(y, 2000), today.year)
        fmt, cur, prv = "%Y", str(y), str(y - 1)
        labels, first, bucket, every = M_SHORT, 1, "%m", 1
        title, ptitle = f"ปี {y + 543}", f"ปี {y - 1 + 543}"
        pa, na = {"year": y - 1}, ({"year": y + 1} if y < today.year else None)
        unit, picker = "รายเดือนในปี", y
    else:
        period = "day"
        try: d0 = date.fromisoformat(args.get("date", ""))
        except ValueError: d0 = today
        d0 = min(d0, today); pv, nx = d0 - timedelta(days=1), d0 + timedelta(days=1)
        fmt, cur, prv = "%Y-%m-%d", d0.isoformat(), pv.isoformat()
        labels, first, bucket, every = [f"{i:02d}" for i in range(24)], 0, "%H", 2
        title, ptitle = f"{d0.day} {M_SHORT[d0.month - 1]} {d0.year + 543}", f"{pv.day} {M_SHORT[pv.month - 1]} {pv.year + 543}"
        pa, na = {"date": pv.isoformat()}, ({"date": nx.isoformat()} if nx <= today else None)
        unit, picker = "รายชั่วโมงในวัน (เวลาไทย)", cur
    size = len(labels)
    a, b = agg(db, fmt, cur), agg(db, fmt, prv)
    s_cur, s_prv = series(db, fmt, cur, bucket, size, first), series(db, fmt, prv, bucket, size, first)
    tops = db.execute(f"""SELECT oi.name, oi.color, SUM(oi.qty) qty, SUM(oi.price*oi.qty*(1+o.vat_rate)) revenue
        FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.status='paid' AND strftime('{fmt}',{L})=?
        GROUP BY oi.name, oi.color ORDER BY revenue DESC, oi.name LIMIT 8""", (cur,)).fetchall()
    orders = db.execute(f"""SELECT o.*, u.username, {L} local_time FROM orders o JOIN users u ON u.id=o.user_id
        WHERE o.status='paid' AND strftime('{fmt}',{L})=? ORDER BY o.id DESC LIMIT 200""", (cur,)).fetchall()
    return dict(period=period, title=title, prev_title=ptitle, unit=unit, picker=picker, cur=a, prev=b,
                change=pct(a["rev"], b["rev"]), prev_args=pa, next_args=na, tops=tops, orders=orders,
                chart=bar_svg(labels, [(ptitle, s_prv, PREV), (title, s_cur, CUR)], f"ยอดขาย{unit}: {title} เทียบ {ptitle}", every),
                top_max=max((t["revenue"] for t in tops), default=0) or 1)

# ---------- ภาพรวมสำหรับหน้า Dashboard: วันนี้ / เดือนนี้ / ปีนี้ + กราฟ 12 เดือนเทียบปีก่อน ----------
def overview_report(db, today):
    y, m = today.year, today.month
    yday = today - timedelta(days=1)
    spec = [("วันนี้", "%Y-%m-%d", today.isoformat(), yday.isoformat(), "เทียบเมื่อวาน"),
            ("เดือนนี้", "%Y-%m", today.strftime("%Y-%m"), (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"), "เทียบเดือนก่อน"),
            ("ปีนี้", "%Y", str(y), str(y - 1), "เทียบปีก่อน")]
    kpis = []
    for lb, fmt, c, p, cmp_ in spec:
        a, b = agg(db, fmt, c), agg(db, fmt, p)
        kpis.append(dict(label=lb, cmp=cmp_, rev=a["rev"], n=a["n"], change=pct(a["rev"], b["rev"])))
    months = [(y, m)]                                              # 12 เดือนล่าสุด (เก่า -> ใหม่)
    for _ in range(11): yy, mm = months[0]; months.insert(0, (yy - 1, 12) if mm == 1 else (yy, mm - 1))
    rev = {r["ym"]: r["rev"] for r in db.execute(f"SELECT strftime('%Y-%m',{L}) ym, SUM(o.total) rev FROM orders o WHERE o.status='paid' GROUP BY ym")}
    now = [rev.get(f"{a:04d}-{b:02d}", 0.0) for a, b in months]
    before = [rev.get(f"{a - 1:04d}-{b:02d}", 0.0) for a, b in months]
    labels = [f"{M_SHORT[b - 1]} {str(a + 543)[2:]}" for a, b in months]
    return dict(kpis=kpis, chart=bar_svg(labels, [("ปีก่อนหน้า", before, PREV), ("12 เดือนล่าสุด", now, CUR)], "ยอดขาย 12 เดือนล่าสุด เทียบช่วงเดียวกันของปีก่อน"),
                has_data=any(now) or any(before))
