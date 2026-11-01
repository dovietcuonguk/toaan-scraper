#!/usr/bin/env python3
"""Đếm số bản án đã công bố của từng TAND cấp huyện (cũ) và TAND khu vực thuộc TP. Hồ Chí Minh,
Hà Nội, Đà Nẵng (cấp "H" trên congbobanan), mọi loại vụ việc, toàn bộ thời gian.
Danh sách Tòa lấy từ probe_levels.json (tools/probe_levels.py). Ghi $TOAAN_WORK/count_lower.json."""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout  # noqa: E402
import scrape_toaan as st  # noqa: E402

WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
OUT = WORK / "count_lower.json"
log = st.build_logger(WORK / "logs" / "count_lower.log")
CITY = {"tp-hcm": "(TAND TP. Hồ Chí Minh", "ha-noi": "(TAND TP. Hà Nội", "da-nang": "(TAND TP Đà Nẵng"}


def courts_of_interest():
    d = json.loads((WORK / "probe_levels.json").read_text(encoding="utf-8"))
    out = []
    for value, text in d["courts"]["H"]["options"]:
        if not value or "quân sự" in text.lower():
            continue
        for key, tag in CITY.items():
            if tag in text:
                kind = "khu-vuc" if "khu vực" in text.lower() else "huyen"
                out.append({"value": value, "name": text.split(" (")[0].strip(), "city": key, "kind": kind})
    return out


def read_total(page):
    txt = page.locator(st.SEL["total_label"]).first.inner_text(timeout=5000)
    digits = re.sub(r"\D", "", txt or "")
    return int(digits) if digits else None


def main():
    todo = courts_of_interest()
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=st.USER_AGENT, locale="vi-VN", viewport={"width": 1280, "height": 800},
                            ignore_https_errors=True)
        ctx.route(re.compile(r"sendpulse\.com"), lambda r: r.abort())
        page = ctx.new_page()
        page.set_default_timeout(45000)
        page.on("dialog", lambda d: d.accept())
        for c in todo:
            if isinstance(res.get(c["value"], {}).get("total"), int):
                continue
            total = None
            for attempt in range(1, 4):
                try:
                    page.goto(st.LISTING_URL, wait_until="networkidle")
                    st.dismiss_popups(page)
                    st.select_level(page, "H", log)
                    st.dismiss_popups(page)
                    st.select_court(page, c["value"], log, top=True)
                    st.click_search(page, log)
                    page.wait_for_function("""(sel) => { const e = document.querySelector(sel);
                        return e && /\\d/.test(e.textContent || ''); }""", arg=st.SEL["total_label"], timeout=90000)
                    total = read_total(page)
                    break
                except Exception as e:  # noqa: BLE001
                    log.warning(f"{c['name']}: lần {attempt} lỗi {e}")
                    time.sleep(5 * attempt)
            res[c["value"]] = {**c, "total": total}
            log.info(f"{c['city']} | {c['name']}: {total}")
            OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
            time.sleep(2)
        b.close()
    print(f"Xong: {len(res)} Tòa, tổng {sum(v['total'] or 0 for v in res.values()):,} bản án")


if __name__ == "__main__":
    main()
