#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tiến độ đợt 2 (phương án A) trên một VPS: bảng Markdown theo từng Tòa trong nhóm của máy.
  (không tham số)  in bảng đầy đủ (upload3.sh ghi lên BANAN PDF/_TIEN_DO_DOT2/TIEN_DO_VPS<k>.md)
  --short          vài dòng tóm tắt (tools/dot2_mac.sh tiendo)
  --pending        số PDF còn chờ xử lý trên máy (0 = xong)
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lower_courts  # noqa: E402

WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
DATA2 = WORK / "data2"


def fmt(n):
    return f"{n:,}".replace(",", ".")


def count_lines(p):
    if not p.exists():
        return 0
    with p.open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def gather():
    k = (WORK / "dot2_vps").read_text().strip() if (WORK / "dot2_vps").exists() else "?"
    courts = []
    cl = WORK / "count_lower.json"
    if cl.exists() and k.isdigit():
        courts = lower_courts.shard(lower_courts.load(cl, ["tp-hcm", "ha-noi", "da-nang"]), 3)[int(k) - 1]
    listed, got, waiting = Counter(), Counter(), 0
    for rf in DATA2.glob("*/*/*/records.jsonl"):
        listed[rf.parent.parent.name] += count_lines(rf)
    for rf in DATA2.glob("*/*/*/records_full.jsonl"):
        v = rf.parent.parent.name
        with rf.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("pdf_path"):
                    got[v] += 1
                    if os.path.exists(r["pdf_path"]):
                        waiting += 1
    proc, methods = Counter(), Counter()
    st = WORK / "state" / "processed2.csv"
    if st.exists():
        with st.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                proc[r["court"]] += 1
                methods[r["status"] if r["status"] != "OK" else r["method"]] += 1
    up_wait = sum(1 for _ in (WORK / "upload2").rglob("*.pdf")) if (WORK / "upload2").exists() else 0
    md_wait = sum(1 for p in (WORK / "md2").rglob("*.md")) if (WORK / "md2").exists() else 0
    md_wait += sum(1 for p in (WORK / "outbox_md").rglob("*.md")) if (WORK / "outbox_md").exists() else 0
    return k, courts, listed, got, waiting, proc, methods, up_wait, md_wait


def svc(name):
    try:
        return subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--short", action="store_true")
    ap.add_argument("--pending", action="store_true")
    a = ap.parse_args()
    k, courts, listed, got, waiting, proc, methods, up_wait, md_wait = gather()
    if a.pending:
        print(waiting)
        return
    free = shutil.disk_usage(str(WORK)).free / 1e9
    tot = sum(c["total"] for c in courts)
    done = sum(proc.values())
    state = ("ĐÃ XONG" if (WORK / "DOT2_ALL_DONE").exists() else
             "đã tải xong danh sách + PDF, đang xử lý/đẩy nốt" if (WORK / "DOWNLOAD2_DONE").exists() else "đang tải")
    svcs = " | ".join(f"{s}: {svc(s)}" for s in ("toaan-lower", "toaan-process2", "toaan-upload3"))
    pdf_up = done - up_wait
    summary = [
        f"VPS{k} — {datetime.now():%d/%m/%Y %H:%M} — {state}",
        f"  Nhóm: {len(courts)} Tòa, {fmt(tot)} bản án trên cổng | đã lấy danh sách {fmt(sum(listed.values()))}"
        f" | đã tải PDF {fmt(sum(got.values()))} | đã đặt tên + MD {fmt(done)} ({done * 100 // max(tot, 1)}%)",
        f"  PDF đã lên Drive {fmt(max(pdf_up, 0))} | chờ đẩy {fmt(up_wait)} | MD chờ MacBook kéo {fmt(md_wait)}"
        f" | ổ trống {free:.1f} GB",
        "  Lớp chữ: " + ", ".join(f"{m} {fmt(n)}" for m, n in sorted(methods.items())),
        f"  {svcs}",
    ]
    if a.short:
        print("\n".join(summary))
        return
    out = ["# Tiến độ đợt 2 — " + summary[0], "", *[s.strip() for s in summary[1:]], "",
           "| Tòa (mã Nơi) | Trên cổng | Đã lấy danh sách | Đã tải PDF | Đã đặt tên + MD |",
           "|---|---:|---:|---:|---:|"]
    for c in sorted(courts, key=lambda c: -c["total"]):
        v = c["value"]
        out.append(f"| {c['ma_noi']} | {fmt(c['total'])} | {fmt(listed[v])} | {fmt(got[v])} | {fmt(proc[v])} |")
    out.append(f"| **Tổng** | **{fmt(tot)}** | **{fmt(sum(listed.values()))}** | **{fmt(sum(got.values()))}** "
               f"| **{fmt(done)}** |")
    lg = WORK / "logs" / "download2.log"
    if lg.exists():
        out += ["", "Nhật ký tải (10 dòng cuối):", "```",
                *lg.read_text(encoding="utf-8", errors="replace").splitlines()[-10:], "```"]
    print("\n".join(out))


if __name__ == "__main__":
    main()
