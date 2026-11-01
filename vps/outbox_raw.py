#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chế độ MacBook tạo MD (cờ /root/work/state/MAC_PROCESS): VPS chỉ tải PDF, MacBook OCR và tạo MD.

  --make     Nếu outbox chưa có lô thô nào: chuyển tối đa --batch PDF chưa xử lý sang
             outbox/raw-<thời điểm>/pdf/<toa>/<loai>/<id>.pdf kèm records.jsonl (bản ghi + court, case_type,
             cap, pdf_rel). Id đã gửi ghi vào state/sent_raw.txt để không gửi lại.
  --pending  In số bản ghi đã có PDF nhưng chưa gửi/chưa xử lý (dùng để biết đã xong toàn bộ chưa).
"""
import argparse
import csv
import json
import os
import shutil
import time
from pathlib import Path

WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
STATE = WORK / "state"
SENT = STATE / "sent_raw.txt"


def load_ids():
    ids = set()
    if SENT.exists():
        ids |= {x.strip() for x in SENT.read_text(encoding="utf-8").split() if x.strip()}
    st = STATE / "processed.csv"
    if st.exists():
        with st.open(encoding="utf-8-sig") as f:
            ids |= {r["id"] for r in csv.DictReader(f)}
    return ids


def candidates(skip):
    for rf in sorted((WORK / "data").glob("*/*/*/records_full.jsonl")):
        court, case_type = rf.parts[-4], rf.parts[-3]
        with rf.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = rec.get("id")
                if not rid or rid in skip or not rec.get("pdf_path") or not os.path.exists(rec["pdf_path"]):
                    continue
                skip.add(rid)
                yield court, case_type, rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--batch", type=int, default=300)
    a = ap.parse_args()
    if a.pending:
        print(sum(1 for _ in candidates(load_ids())))
        return
    outbox = WORK / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    for p in outbox.glob(".raw-*"):  # lô ghi dở do bị dừng giữa chừng: hoàn tất để không mất bản ghi đã gửi
        if (p / "records.jsonl").exists():
            p.rename(outbox / p.name[1:])
    if any(p.name.startswith("raw-") for p in outbox.iterdir()):
        return
    out = outbox / f"raw-{time.strftime('%Y%m%d%H%M%S')}"
    tmp = outbox / f".{out.name}"
    n = 0
    with SENT.open("a", encoding="utf-8") as sent:
        for court, case_type, rec in candidates(load_ids()):
            rel = f"pdf/{court}/{case_type}/{rec['id']}.pdf"
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(rec["pdf_path"], tmp / rel)
            rec.update({"court": court, "case_type": case_type, "cap": "tinh", "pdf_rel": rel})
            with (tmp / "records.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            sent.write(rec["id"] + "\n")
            sent.flush()
            n += 1
            if n >= a.batch:
                break
    if n:
        tmp.rename(out)  # đổi tên khi lô đã đủ: MacBook không kéo lô đang ghi dở


if __name__ == "__main__":
    main()
