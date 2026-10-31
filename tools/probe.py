#!/usr/bin/env python3
"""Chạy thử: kiểm tra máy chủ GitHub có truy cập được congbobanan.toaan.gov.vn
và liệt kê các bộ lọc (select) trên trang tìm kiếm, kể cả danh sách Tòa án.

Chỉ in ra cấu trúc biểu mẫu tìm kiếm (id, tên, các lựa chọn), không in nội dung bản án.
"""
import json
import re
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

BASE_URL = "https://congbobanan.toaan.gov.vn"
LISTING_URL = f"{BASE_URL}/0tat1cvn/ban-an-quyet-dinh"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
COURT_RE = re.compile(r"(Hồ Chí Minh|Hà Nội|Đà Nẵng)", re.I)


def step(msg):
    print(f"\n=== {msg}", flush=True)


def main():
    step("1. HTTP GET trang danh sách (không dùng trình duyệt)")
    try:
        t = time.time()
        r = httpx.get(LISTING_URL, headers={"User-Agent": UA}, timeout=60, follow_redirects=True)
        print(f"status={r.status_code} bytes={len(r.content)} time={time.time()-t:.1f}s")
    except Exception as e:  # noqa: BLE001
        print(f"LỖI HTTP: {e!r}")

    step("2. Mở trang bằng Chromium (Playwright)")
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent=UA, locale="vi-VN", viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        try:
            resp = page.goto(LISTING_URL, wait_until="networkidle", timeout=90000)
            print(f"status={resp.status if resp else None} title={page.title()!r}")
        except Exception as e:  # noqa: BLE001
            print(f"LỖI mở trang: {e!r}")
            b.close()
            sys.exit(1)

        step("3. Các ô select trên trang")
        selects = page.evaluate(
            """() => Array.from(document.querySelectorAll('select')).map(s => ({
                id: s.id, name: s.name,
                visible: !!(s.offsetWidth || s.offsetHeight || s.getClientRects().length),
                n: s.options.length,
                sample: Array.from(s.options).slice(0, 6).map(o => [o.value, o.text.trim()]),
                opts: Array.from(s.options).map(o => [o.value, o.text.trim()])
            }))"""
        )
        for s in selects:
            print(json.dumps({k: s[k] for k in ("id", "name", "visible", "n", "sample")}, ensure_ascii=False))

        step("4. Lựa chọn khớp tên Tòa (Hồ Chí Minh / Hà Nội / Đà Nẵng)")
        for s in selects:
            hits = [o for o in s["opts"] if COURT_RE.search(o[1])]
            if hits:
                print(f"select id={s['id']}:")
                for v, txt in hits[:40]:
                    print(f"   value={v!r}  text={txt!r}")

        step("5. Các ô input ngày / từ khóa")
        inputs = page.evaluate(
            """() => Array.from(document.querySelectorAll('input')).filter(i => i.type !== 'hidden')
                 .map(i => ({id: i.id, type: i.type, ph: i.placeholder,
                    visible: !!(i.offsetWidth || i.offsetHeight)}))"""
        )
        for i in inputs:
            print(json.dumps(i, ensure_ascii=False))

        step("6. Tổng số bản ghi hiển thị mặc định")
        try:
            print(page.locator("#ctl00_Content_home_Public_ctl00_lbl_count_record").first.inner_text())
        except Exception as e:  # noqa: BLE001
            print(f"(không đọc được: {e!r})")
        b.close()


if __name__ == "__main__":
    main()
