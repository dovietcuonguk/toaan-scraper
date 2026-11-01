#!/usr/bin/env python3
"""Liệt kê các cấp xét xử (Drop_Levels) và danh sách Tòa thuộc từng cấp trên congbobanan,
để xác định mã Tòa cấp huyện và TAND khu vực của TP. Hồ Chí Minh, Hà Nội, Đà Nẵng.
Ghi kết quả ra $TOAAN_WORK/probe_levels.json. Chỉ đọc biểu mẫu tìm kiếm, không tải bản án."""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright  # noqa: E402
import scrape_toaan as st  # noqa: E402

OUT = Path(os.environ.get("TOAAN_WORK", "/root/work")) / "probe_levels.json"
log = st.build_logger(Path(os.environ.get("TOAAN_WORK", "/root/work")) / "logs" / "probe_levels.log")


def courts(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('select'))
        .filter(s => /Drop_Courts/i.test(s.id) && s.id.endsWith('_top'))
        .flatMap(s => Array.from(s.options).map(o => [o.value, o.text.trim()]))""")


with sync_playwright() as p:
    b = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(user_agent=st.USER_AGENT, locale="vi-VN", viewport={"width": 1280, "height": 800},
                        ignore_https_errors=True)
    ctx.route(re.compile(r"sendpulse\.com"), lambda r: r.abort())
    page = ctx.new_page()
    page.set_default_timeout(45000)
    page.goto(st.LISTING_URL, wait_until="networkidle")
    st.dismiss_popups(page)
    levels = page.evaluate(f"""() => Array.from(document.querySelector('{st.SEL["level"]}').options)
        .map(o => [o.value, o.text.trim()])""")
    result = {"levels": levels, "courts": {}}
    for value, label in levels:
        if not value:
            continue
        page.goto(st.LISTING_URL, wait_until="networkidle")
        st.dismiss_popups(page)
        st.select_level(page, value, log)
        result["courts"][value] = {"label": label, "options": courts(page)}
        log.info(f"Cấp {value} ({label}): {len(result['courts'][value]['options'])} Tòa")
    b.close()
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"Đã ghi {OUT}")
