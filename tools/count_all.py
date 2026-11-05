#!/usr/bin/env python3
"""Đếm số bản án đã công bố của MỌI TAND cấp tỉnh (cấp "T") và TAND cấp huyện / TAND khu vực (cấp "H")
trên congbobanan, toàn thời gian, mọi loại vụ việc — để lên kế hoạch tải toàn quốc.

Danh sách Tòa lấy từ $TOAAN_WORK/probe_levels.json (tools/probe_levels.py). Bỏ Tòa quân sự và (mặc định)
các Tòa của TP. Hồ Chí Minh, Hà Nội, Đà Nẵng (đã đếm/tải ở đợt 1, đợt 2; --all để đếm cả).
Chia việc cho nhiều VPS: --shard K/N (xen kẽ theo thứ tự). Chạy lại được (bỏ qua Tòa đã đếm).
Kết quả: $TOAAN_WORK/count_all_<K>.json, sao lên Drive BANAN PDF/_TIEN_DO_DOT2/ (remote rclone "banan")."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright  # noqa: E402
import scrape_toaan as st  # noqa: E402

WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
DONE_CITY_T = {"787", "784", "775"}  # TAND TP. HCM, TP. Hà Nội, TP Đà Nẵng
CITY_TAGS = ("(TAND TP. Hồ Chí Minh", "(TAND TP. Hà Nội", "(TAND TP Đà Nẵng")


def court_list(include_all):
    d = json.loads((WORK / "probe_levels.json").read_text(encoding="utf-8"))
    out = []
    for lv in ("T", "H"):
        for value, text in d["courts"].get(lv, {}).get("options", []):
            if not value or "quân sự" in text.lower():
                continue
            if not include_all and ((lv == "T" and value in DONE_CITY_T) or any(t in text for t in CITY_TAGS)):
                continue
            m = re.search(r"\((.+?)\s*\)\s*$", text)
            parent = m.group(1).strip() if m else text
            kind = "tinh" if lv == "T" else ("khu-vuc" if "khu vực" in text.lower() else "huyen")
            out.append({"level": lv, "value": value, "name": text.split(" (")[0].strip(), "parent": parent,
                        "kind": kind})
    out.sort(key=lambda c: (c["level"], int(c["value"]) if c["value"].isdigit() else 0))
    return out


def read_total(page):
    txt = page.locator(st.SEL["total_label"]).first.inner_text(timeout=5000)
    digits = re.sub(r"\D", "", txt or "")
    return int(digits) if digits else None


def push(path):
    subprocess.run(["rclone", "copyto", str(path), f"banan:_TIEN_DO_DOT2/{path.name}", "--log-level", "ERROR"],
                   check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", default="1/1")
    ap.add_argument("--all", action="store_true", help="đếm cả Tòa của 3 thành phố đã tải")
    a = ap.parse_args()
    k, n = (int(x) for x in a.shard.split("/"))
    courts = [c for i, c in enumerate(court_list(a.all)) if i % n == k - 1]
    out = WORK / f"count_all_{k}.json"
    res = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    log = st.build_logger(WORK / "logs" / f"count_all_{k}.log")
    log.info(f"Máy {k}/{n}: {len(courts)} Tòa, đã đếm trước {len(res)}")
    t0, done_now = time.time(), 0
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=st.USER_AGENT, locale="vi-VN", viewport={"width": 1280, "height": 800},
                            ignore_https_errors=True)
        ctx.route(re.compile(r"sendpulse\.com"), lambda r: r.abort())
        page = ctx.new_page()
        page.set_default_timeout(45000)
        page.on("dialog", lambda dlg: dlg.accept())
        for c in courts:
            key = f"{c['level']}:{c['value']}"
            if isinstance(res.get(key, {}).get("total"), int):
                continue
            total, err = None, ""
            for attempt in (1, 2):
                try:
                    page.goto(st.LISTING_URL, wait_until="networkidle")
                    st.dismiss_popups(page)
                    st.select_level(page, c["level"], log)
                    st.dismiss_popups(page)
                    st.select_court(page, c["value"], log, top=True)
                    st.click_search(page, log)
                    page.wait_for_function("""(sel) => { const e = document.querySelector(sel);
                        return e && /\\d/.test(e.textContent || ''); }""", arg=st.SEL["total_label"], timeout=60000)
                    total = read_total(page)
                    break
                except Exception as e:  # noqa: BLE001
                    err = str(e).splitlines()[0][:120]
                    log.warning(f"{c['name']}: lần {attempt} lỗi {err}")
                    time.sleep(5)
            res[key] = {**c, "total": total, "note": "" if total is not None else f"không đọc được (0 hoặc lỗi): {err}"}
            done_now += 1
            log.info(f"[{len(res)}/{len(courts)}] {c['parent']} | {c['name']}: {total}")
            out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
            if done_now % 20 == 0:
                push(out)
            time.sleep(2)
        b.close()
    push(out)
    log.info(f"XONG máy {k}: {len(res)} Tòa, tổng {sum(v['total'] or 0 for v in res.values()):,} bản án, "
             f"{(time.time() - t0) / 3600:.1f} giờ")


if __name__ == "__main__":
    main()
