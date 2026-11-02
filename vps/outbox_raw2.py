#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Đợt 2 (cấp huyện/khu vực): gửi lô PDF thô cho MacBook tạo MD.

Khác đợt 1: PDF được GIỮ LẠI trên VPS (liên kết cứng vào lô gửi đi) để VPS tự đẩy thẳng lên
Google Drive sau khi MacBook báo tên file cuối cùng (vps/upload_pdf2.py).
  --make     tạo lô outbox/raw2-<thời điểm> (tối đa --batch bản ghi) nếu chưa có lô raw2 nào chờ
  --pending  số bản ghi đã có PDF nhưng chưa gửi
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lower_courts  # noqa: E402

WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
SENT = WORK / "state" / "sent_raw2.txt"


def candidates(skip):
    for rf in sorted((WORK / "data2").glob("*/*/*/records_full.jsonl")):
        cj = rf.parent / "court.json"
        if not cj.exists():
            continue
        court = json.loads(cj.read_text(encoding="utf-8"))
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
                yield court, rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--batch", type=int, default=300)
    a = ap.parse_args()
    skip = set(SENT.read_text(encoding="utf-8").split()) if SENT.exists() else set()
    if a.pending:
        print(sum(1 for _ in candidates(skip)))
        return
    outbox = WORK / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    for p in outbox.glob(".raw2-*"):
        if (p / "records.jsonl").exists():
            p.rename(outbox / p.name[1:])
    if any(p.name.startswith("raw2-") for p in outbox.iterdir()):
        return
    out = outbox / f"raw2-{time.strftime('%Y%m%d%H%M%S')}"
    tmp = outbox / f".{out.name}"
    n = 0
    SENT.parent.mkdir(parents=True, exist_ok=True)
    with SENT.open("a", encoding="utf-8") as sent:
        for court, rec in candidates(skip):
            rel = f"pdf/{court['value']}/{rec['id']}.pdf"
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            os.link(rec["pdf_path"], tmp / rel)  # liên kết cứng: không tốn thêm ổ, bản gốc giữ để đẩy lên Drive
            rec.update({"court": court["city"], "case_type": lower_courts.case_type_of(rec), "cap": court["kind"],
                        "ma_noi": court["ma_noi"], "toa_an_xet_xu": rec.get("toa_an_xet_xu") or court["name"],
                        "pdf_rel": rel})
            with (tmp / "records.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            sent.write(rec["id"] + "\n")
            sent.flush()
            n += 1
            if n >= a.batch:
                break
    if n:
        tmp.rename(out)


if __name__ == "__main__":
    main()
