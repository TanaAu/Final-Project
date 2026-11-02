/* ============ app.js — สคริปต์ฝั่งเบราว์เซอร์ ============ */
// 1) แถบเลื่อนอัตโนมัติทุก 5 วินาที (เฉพาะหน้าที่มี .carousel)
const car = document.querySelector('.carousel');
if (car) {
  const track = car.querySelector('.track'), n = track.children.length, dots = car.querySelectorAll('.dots i');
  let i = 0, timer;
  const go = k => { i = (k + n) % n; track.style.transform = `translateX(-${i * 100}%)`; dots.forEach((d, j) => d.classList.toggle('on', j === i)); };
  const start = () => timer = setInterval(() => go(i + 1), 5000);   // 5000 ms = 5 วินาที
  dots.forEach((d, j) => d.onclick = () => { clearInterval(timer); go(j); start(); });
  let x0; car.ontouchstart = e => x0 = e.touches[0].clientX;          // ปัดนิ้วบนมือถือ
  car.ontouchend = e => { const d = e.changedTouches[0].clientX - x0; if (Math.abs(d) > 40) { clearInterval(timer); go(i + (d < 0 ? 1 : -1)); start(); } };
  go(0); start();
}
// 2) ปุ่มแว่นขยาย: เปิด/ปิดช่องค้นหา
const sb = document.getElementById('searchbtn');
if (sb) sb.onclick = () => { const b = document.getElementById('searchbox'); b.classList.toggle('open'); b.querySelector('input').focus(); };

/* ================= ส่วนเพิ่มรอบนี้ ================= */
(() => {
  // 3) ปุ่ม แสดง/ซ่อน รหัสผ่าน: ครอบทุกช่อง input[type=password] ในเว็บ (ล็อกอิน สมัคร ตั้งรหัสใหม่ ADMIN)
  document.querySelectorAll('input[type=password]').forEach(inp => {
    const wrap = document.createElement('div'); wrap.className = 'pw';
    inp.parentNode.insertBefore(wrap, inp); wrap.appendChild(inp);
    const b = document.createElement('button'); b.type = 'button'; b.className = 'pw-btn';
    b.textContent = 'แสดง'; b.setAttribute('aria-label', 'แสดงรหัสผ่าน'); b.setAttribute('aria-pressed', 'false');
    b.onclick = () => {
      const show = inp.type === 'password'; inp.type = show ? 'text' : 'password';
      b.textContent = show ? 'ซ่อน' : 'แสดง'; b.setAttribute('aria-pressed', String(show));
      b.setAttribute('aria-label', show ? 'ซ่อนรหัสผ่าน' : 'แสดงรหัสผ่าน');
    };
    wrap.appendChild(b);
  });

  // 4) คำใบ้ตอนพิมพ์ค้นหา: ทุกช่องที่มี data-suggest เรียก /api/suggest?q=... (รอ 180ms หลังหยุดพิมพ์)
  document.querySelectorAll('input[data-suggest]').forEach(inp => {
    const host = inp.form || inp.parentNode; host.classList.add('sug-host');
    const box = document.createElement('ul'); box.className = 'sug'; box.hidden = true; box.setAttribute('role', 'listbox'); host.appendChild(box);
    let items = [], active = -1, timer, seq = 0;
    const close = () => { box.hidden = true; active = -1; };
    const mark = () => [...box.children].forEach((li, i) => li.classList.toggle('on', i === active));
    const render = () => {
      box.replaceChildren();
      items.forEach(it => {                                   // ใช้ textContent เสมอ กันสคริปต์แปลกปลอม
        const li = document.createElement('li'); li.setAttribute('role', 'option');
        const t = document.createElement('span'); t.className = 'sug-t'; t.textContent = it.type;
        const l = document.createElement('span'); l.className = 'sug-l'; l.textContent = it.label; li.append(t, l);
        if (it.sub) { const s = document.createElement('span'); s.className = 'sug-s'; s.textContent = it.sub; li.append(s); }
        li.onmousedown = e => { e.preventDefault(); location.href = it.url; };
        box.append(li);
      });
      box.style.top = (inp.offsetTop + inp.offsetHeight + 4) + 'px'; box.style.left = inp.offsetLeft + 'px';
      box.style.width = Math.max(inp.offsetWidth, 260) + 'px'; box.hidden = !items.length;
    };
    inp.addEventListener('input', () => {
      clearTimeout(timer); const q = inp.value.trim();
      if (!q) { items = []; close(); return; }
      timer = setTimeout(async () => {
        const my = ++seq;
        try { const r = await fetch('/api/suggest?q=' + encodeURIComponent(q)); const d = await r.json(); if (my === seq) { items = d; active = -1; render(); } } catch (e) {}
      }, 180);
    });
    inp.addEventListener('keydown', e => {                    // ลูกศรขึ้นลงเลือกคำใบ้ / Enter เปิด / Esc ปิด
      if (box.hidden) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); active = (active + 1) % items.length; mark(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); active = (active - 1 + items.length) % items.length; mark(); }
      else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); location.href = items[active].url; }
      else if (e.key === 'Escape') close();
    });
    inp.addEventListener('blur', () => setTimeout(close, 120));
  });

  // 5) หน้าสินค้า: เลือกสี -> เปลี่ยนรูปและจำนวนคงเหลือตามสีนั้น
  const pimg = document.getElementById('pimg'), pst = document.getElementById('pstock');
  document.querySelectorAll('.colors input[type=radio]').forEach(r => {
    const apply = () => {
      if (!r.checked) return;
      if (pimg && r.dataset.img) { pimg.src = r.dataset.img; pimg.hidden = false; }
      if (pst) pst.textContent = 'คงเหลือ ' + r.dataset.stock + ' ชิ้น';
    };
    r.addEventListener('change', apply); apply();
  });

  // 6) หน้า ADMIN แก้สินค้า: ปุ่ม "+ เพิ่มสี" คัดลอกแถวเปล่า / ปุ่ม "ลบสี" เอาแถวออก
  const add = document.getElementById('add-color'), tpl = document.getElementById('color-row-tpl'), rows = document.getElementById('color-rows');
  if (add && tpl && rows) {
    add.onclick = () => rows.appendChild(tpl.content.cloneNode(true));
    rows.addEventListener('click', e => { if (e.target.classList.contains('rm-color')) e.target.closest('.color-row').remove(); });
  }
})();

/* ===== ติดตามการจัดส่งแบบ Real time (หน้า "คำสั่งซื้อของฉัน") =====
   ทุก 5 วินาที ถาม /api/tracking ว่าแต่ละออเดอร์มี "รหัสอัปเดต" (ขั้นตอน:จำนวนข้อความ) เปลี่ยนไหม
   ถ้าเปลี่ยน -> ดึงส่วนแสดงผลใหม่ของออเดอร์นั้นจาก /order/<id>/tracking มาแทนที่ทันที โดยไม่ต้องรีเฟรชหน้า */
(() => {
  if (!document.querySelector('.ship[data-oid]')) return;
  const tick = async () => {
    if (document.hidden) return;                                   // แท็บไม่ได้เปิดอยู่ ไม่ต้องถาม
    try {
      const d = await (await fetch('/api/tracking', { cache: 'no-store' })).json();
      for (const box of document.querySelectorAll('.ship[data-oid]')) {
        const sig = d[box.dataset.oid];
        if (sig && sig !== box.dataset.sig) {
          const html = await (await fetch('/order/' + box.dataset.oid + '/tracking', { cache: 'no-store' })).text();
          const t = document.createElement('div'); t.innerHTML = html.trim();
          const n = t.firstElementChild; if (n) { box.replaceWith(n); n.classList.add('flash-new'); }
        }
      }
    } catch (e) {}
  };
  setInterval(tick, 5000);
})();
