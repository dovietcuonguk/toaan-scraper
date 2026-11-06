#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Đợt 2: tải bù PDF cho những mã đã có trong danh sách nhưng CHƯA được đặt tên + tạo MD và không còn PDF trên VPS.

Đo 06/11 trên VPS3: HN-KV9 thiếu 813, HN-KV12 thiếu 763 mã — có trong records_full.jsonl nhưng file PDF không còn,
không có dòng nào trong processed2.csv, không có MD trên MacBook. Không sửa được bằng cách chạy lại tải thường vì
nhóm đã đánh dấu XONG và fetch_pdfs.py bỏ qua mã đã có dòng trong records_full.jsonl.

Cách làm (mỗi mã chỉ tải lại ở MỘT nhóm — nhóm đầu tiên liệt kê nó):
  - mã "cần tải": có trong records.jsonl, chưa có dòng trong processed2.csv (mọi trạng thái), không có PDF ở bất kỳ
    nhóm nào, và cổng có PDF (pdf_url khác rỗng) hoặc chưa từng tải trang chi tiết;
  - bỏ dòng records_full.jsonl của mã đó ở nhóm được chọn (ghi tệp tạm rồi đổi tên), chạy fetch_pdfs.py cho nhóm;
  - toaan-process2 (đang chạy) tự đặt tên + tạo MD, toaan-upload3 đẩy PDF lên Drive, MacBook kéo MD (keo).
--dem   chỉ đếm, in theo Tòa (không thay đổi gì)
"""
import argparse
import collections
import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
DATA2 = WORK / "data2"
STATE_CSV = WORK / "state" / "processed2.csv"
LOG = WORK / "logs" / "tai_bu.log"


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_jsonl(p):
    out = []
    if p.exists():
        with p.open(encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def plan():
    xuly = set()
    if STATE_CSV.exists():
        with STATE_CSV.open(encoding="utf-8-sig") as f:
            xuly = {r["id"] for r in csv.DictReader(f)}
    dirs = sorted(d for d in DATA2.glob("*/*/*") if (d / "records.jsonl").exists() and (d / "court.json").exists())
    full, co_pdf, co_dong, co_url = {}, set(), set(), set()
    for d in dirs:
        full[d] = read_jsonl(d / "records_full.jsonl")
        for r in full[d]:
            i = r.get("id")
            co_dong.add(i)
            if r.get("pdf_url"):
                co_url.add(i)
            if r.get("pdf_path") and os.path.exists(r["pdf_path"]):
                co_pdf.add(i)
    xong = xuly | co_pdf
    viec, da_chon = {}, set()
    for d in dirs:
        can = set()
        for r in read_jsonl(d / "records.jsonl"):
            i = r.get("id")
            # bỏ qua mã cổng không có PDF (đã tải trang chi tiết, pdf_url rỗng ở mọi nhóm)
            if i and i not in xong and i not in da_chon and (i in co_url or i not in co_dong):
                can.add(i)
        if can:
            da_chon |= can
            viec[d] = can
    return viec, full


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dem", action="store_true")
    a = ap.parse_args()
    viec, full = plan()
    theo_toa = collections.Counter()
    for d, can in viec.items():
        c = json.loads((d / "court.json").read_text(encoding="utf-8"))
        theo_toa[c.get("ma_noi") or c["value"]] += len(can)
    tong = sum(theo_toa.values())
    if a.dem:
        print(f"Cần tải bù {tong:,} mã ở {len(viec)} nhóm" + (":" if tong else ""))
        for m, n in theo_toa.most_common(25):
            print(f"   {m}: {n:,}")
        return
    if not tong:
        log("Không có mã nào cần tải bù.")
        return
    (WORK / "DOT2_ALL_DONE").unlink(missing_ok=True)  # để keo / ocr2 không coi là đã xong khi còn bản mới
    log(f"===== Tải bù {tong:,} mã ở {len(viec)} nhóm: {dict(theo_toa.most_common(10))} =====")
    py = str(REPO / ".venv" / "bin" / "python")
    for k, (d, can) in enumerate(sorted(viec.items()), 1):
        rf = d / "records_full.jsonl"
        if rf.exists():
            keep = [r for r in full[d] if r.get("id") not in can]
            tmp = rf.with_name(".records_full.jsonl.tmp")
            tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep), encoding="utf-8")
            os.replace(tmp, rf)
        prev = None
        for _ in range(4):
            subprocess.run([py, "fetch_pdfs.py", "--records-dir", str(d), "--delay", "0.8"], cwd=REPO,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            got = {r.get("id") for r in read_jsonl(rf) if r.get("pdf_path")}
            rem = len(can - got)
            if rem == 0 or rem == prev:
                break
            prev = rem
        log(f"  [{k}/{len(viec)}] {d.relative_to(DATA2)}: tải {len(can) - rem}/{len(can)}"
            + (f" (còn {rem} không tải được)" if rem else ""))
    log("===== Tải bù xong; toaan-process2 sẽ đặt tên + tạo MD, toaan-upload3 đẩy lên Drive =====")


if __name__ == "__main__":
    main()
