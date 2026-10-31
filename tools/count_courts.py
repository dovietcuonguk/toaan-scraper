#!/usr/bin/env python3
"""Đếm số bản án/quyết định đã công bố của TAND cấp tỉnh tại TP. Hồ Chí Minh,
Hà Nội, Đà Nẵng, theo từng loại vụ việc (không lọc ngày, tức từ 07/2017 đến nay).

Dùng để chạy thử trên VPS đặt tại Việt Nam: vừa kiểm tra cổng có cho truy cập
không, vừa ước lượng khối lượng tải. Chỉ đọc số lượng, không tải bản án nào.

Dùng lại các hàm đã kiểm chứng trong scrape_toaan.py (chọn cấp xét xử, loại
vụ việc, bấm tìm kiếm, ẩn popup).
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout  # noqa: E402

import scrape_toaan as st  # noqa: E402

LEVEL_TINH = "T"  # "TAND cấp tỉnh" trong dropdown Drop_Levels
COURTS = {
    "tp-hcm": r"H[ồô] Ch[íi] Minh",
    "ha-noi": r"H[àa] N[ộo]i",
    "da-nang": r"[ĐD][àa] N[ẵa]ng",
}
OUT = Path.home() / "count_result.json"

log = st.build_logger(Path.home() / "count_courts.log")


def court_selects(page):
    """Liệt kê các <select> chọn Tòa (id chứa 'Drop_Courts')."""
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('select'))
            .filter(s => /Drop_Courts/i.test(s.id))
            .map(s => ({id: s.id,
                        visible: !!(s.offsetWidth || s.offsetHeight || s.getClientRects().length),
                        opts: Array.from(s.options).map(o => [o.value, o.text.trim()])}))"""
    )


def select_court(page, pattern: str):
    """Chọn Tòa có tên khớp pattern (loại trừ 'cấp cao'). Trả về (id_select, value, text)."""
    sels = court_selects(page)
    sels.sort(key=lambda s: (not s["visible"], "_top" not in s["id"]))
    rx = re.compile(pattern, re.I)
    for s in sels:
        for value, text in s["opts"]:
            if value and rx.search(text) and "cao" not in text.lower():
                sel_id = "#" + s["id"]
                if s["visible"]:
                    try:
                        with page.expect_response(
                            lambda r: r.request.method == "POST"
                            and r.url.split("?")[0].rstrip("/") == st.LISTING_URL.rstrip("/"),
                            timeout=10000,
                        ):
                            page.select_option(sel_id, value=value)
                    except PWTimeout:
                        pass
                else:
                    st._set_select_value_js(page, sel_id, value)
                page.wait_for_timeout(1500)
                return s["id"], value, text
    return None


def read_total(page):
    try:
        txt = page.locator(st.SEL["total_label"]).first.inner_text(timeout=5000)
        digits = re.sub(r"\D", "", txt or "")
        return int(digits) if digits else None
    except Exception:  # noqa: BLE001
        return None


def count_one(page, court_pattern, case_label):
    for attempt in range(1, 4):
        if attempt == 1:
            page.goto(st.LISTING_URL, wait_until="networkidle")
        else:
            page.reload(wait_until="networkidle")
        st.dismiss_popups(page)
        st.select_level(page, LEVEL_TINH, log)
        st.dismiss_popups(page)
        chosen = select_court(page, court_pattern)
        if not chosen:
            return None, "không tìm thấy Tòa trong danh sách"
        st.select_case_type(page, case_label, log)
        st.click_search(page, log)
        try:
            page.wait_for_function(
                """(sel) => { const e = document.querySelector(sel);
                               return e && /\\d/.test(e.textContent || ''); }""",
                arg=st.SEL["total_label"],
                timeout=90000,
            )
            return read_total(page), f"{chosen[2]} (value={chosen[1]})"
        except PWTimeout:
            log.warning(f"  chưa thấy tổng số (lần {attempt}/3), thử lại...")
            time.sleep(3 * attempt)
    return None, "không đọc được tổng số sau 3 lần thử"


def main():
    results = {}
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        # Cổng không gửi kèm chứng chỉ trung gian; Chromium trên Linux dùng kho chứng chỉ
        # riêng (NSS) nên có thể báo lỗi chứng chỉ dù hệ điều hành đã được bổ sung.
        ctx = browser.new_context(user_agent=st.USER_AGENT, locale="vi-VN",
                                  viewport={"width": 1280, "height": 800},
                                  ignore_https_errors=True)
        ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        ctx.route(re.compile(r"sendpulse\.com"), lambda route: route.abort())
        page = ctx.new_page()
        page.set_default_timeout(45000)
        page.on("dialog", lambda d: d.accept())

        # Thông tin dropdown chọn Tòa sau khi chọn cấp tỉnh (để kiểm tra tên Tòa)
        page.goto(st.LISTING_URL, wait_until="networkidle")
        st.dismiss_popups(page)
        st.select_level(page, LEVEL_TINH, log)
        for s in court_selects(page):
            hits = [o for o in s["opts"] if re.search("|".join(COURTS.values()), o[1], re.I)]
            log.info(f"Dropdown Tòa {s['id']} visible={s['visible']} n={len(s['opts'])} khớp={hits}")

        for court_key, pattern in COURTS.items():
            results[court_key] = {}
            for case_key, case_label in st.CASE_TYPES.items():
                n, note = count_one(page, pattern, case_label)
                results[court_key][case_key] = n
                log.info(f"[{court_key}] {case_label}: {n}  ({note})")
                OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()

    print("\n========== KẾT QUẢ ĐẾM (TAND cấp tỉnh, toàn bộ thời gian) ==========")
    grand = 0
    for court_key, by_type in results.items():
        sub = sum(v for v in by_type.values() if isinstance(v, int))
        grand += sub
        print(f"\n{court_key}: tổng {sub:,}")
        for case_key, n in by_type.items():
            print(f"   {case_key:<24} {n if n is not None else 'LỖI'}")
    print(f"\nTỔNG CỘNG 3 TÒA: {grand:,} bản án/quyết định")
    print(f"Thời gian chạy: {(time.time()-t0)/60:.1f} phút. Kết quả lưu tại {OUT}")


if __name__ == "__main__":
    main()
