#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In bảng tiến độ (Markdown) cho việc tải bản án TAND cấp tỉnh trên VPS."""
import csv
import json
import os
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
FIELDNAMES = ["id", "court", "case_type", "status", "final_stem", "dest_dir", "method", "note", "timestamp"]
NAMES = {"tp-hcm": "TAND TP. Hồ Chí Minh", "ha-noi": "TAND TP. Hà Nội", "da-nang": "TAND TP. Đà Nẵng"}


def ids_in(path_glob, need_pdf=False):
    ids = set()
    for p in WORK.glob(path_glob):
        with p.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("id") and (not need_pdf or r.get("pdf_url")):
                        ids.add(r["id"])
    return ids


def vn(n):
    return f"{n:,}".replace(",", ".")


def main():
    expected = json.loads((REPO / "vps" / "expected_counts.json").read_text(encoding="utf-8"))
    done = defaultdict(int)
    ocr = defaultdict(int)
    issues = defaultdict(int)
    for st in (WORK / "state" / "processed.csv", WORK / "state" / "processed_mac.csv"):
        if not st.exists():
            continue
        with st.open(encoding="utf-8-sig") as f:
            # processed_mac.csv (MacBook gửi về) không có dòng tiêu đề
            rd = csv.DictReader(f, fieldnames=FIELDNAMES) if st.name == "processed_mac.csv" else csv.DictReader(f)
            for row in rd:
                if row.get("id") in (None, "id") or not row.get("court"):
                    continue
                k = (row["court"], row["case_type"])
                if row["status"] in ("OK", "THIEU"):
                    done[k] += 1
                if row["method"] == "OCR":
                    ocr[k] += 1
                if row["status"] != "OK" or row["note"]:
                    issues[k] += 1

    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    out = [f"# Tiến độ tải bản án TAND cấp tỉnh", "", f"Cập nhật lúc: **{now}** (giờ Việt Nam)", ""]
    if (WORK / "ALL_DONE").exists():
        out += ["**TRẠNG THÁI: ĐÃ HOÀN TẤT TOÀN BỘ.**", ""]
    elif (WORK / "DOWNLOAD_DONE").exists():
        out += ["Trạng thái: đã tải xong danh sách và PDF; đang xử lý/đẩy nốt lên Drive.", ""]
    else:
        out += ["Trạng thái: đang tải.", ""]
    out += ["| Tòa | Loại vụ việc | Trên cổng | Đã lấy danh sách | Đã tải PDF | Đã xử lý (MD) | Dùng OCR | Cần xem lại |",
            "|---|---|---:|---:|---:|---:|---:|---:|"]
    tot = defaultdict(int)
    for court, by_ct in expected.items():
        if court.startswith("_"):
            continue
        for ct, n in by_ct.items():
            listed = len(ids_in(f"data/{court}/{ct}/*/records.jsonl"))
            fetched = len(ids_in(f"data/{court}/{ct}/*/records_full.jsonl", need_pdf=True))
            k = (court, ct)
            out.append(f"| {NAMES[court]} | {ct} | {vn(n)} | {vn(listed)} | {vn(fetched)} | {vn(done[k])} | {vn(ocr[k])} | {vn(issues[k])} |")
            for key, v in (("n", n), ("listed", listed), ("fetched", fetched), ("done", done[k])):
                tot[key] += v
    pct = 100 * tot["done"] / tot["n"] if tot["n"] else 0
    out += [f"| **Tổng** | | **{vn(tot['n'])}** | **{vn(tot['listed'])}** | **{vn(tot['fetched'])}** | **{vn(tot['done'])}** | | |",
            "", f"Hoàn thành: **{pct:.1f}%** số bản án trên cổng đã có file MD trên Drive.", ""]
    du = shutil.disk_usage("/")
    out += [f"Ổ đĩa máy chủ: còn trống {du.free / 1e9:.1f} GB / {du.total / 1e9:.1f} GB.", ""]
    log = WORK / "logs" / "download.log"
    if log.exists():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]
        out += ["Nhật ký gần nhất:", "", "```", *tail, "```"]
    print("\n".join(out))


if __name__ == "__main__":
    main()
