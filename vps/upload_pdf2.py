#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Đợt 2 (phương án B): VPS tự đẩy PDF bản án cấp huyện/khu vực thẳng lên Google Drive "BANAN PDF".

MacBook tạo MD và gửi về state/processed_mac.csv tên file cuối cùng (final_stem) + thư mục (dest_dir).
Với mỗi bản ghi đợt 2 đã có tên mà chưa đẩy: liên kết cứng PDF gốc vào upload2/<dest_dir>/<final_stem>.pdf,
rồi `rclone move` lên Drive (gốc = thư mục BANAN PDF). Đẩy xong thì xóa PDF gốc trên VPS cho nhẹ ổ.
  --loop     chạy mãi, mỗi --every giây một lượt (dịch vụ toaan-upload2)
  --status   in bảng tiến độ đợt 2 theo từng Tòa
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
STATE = WORK / "state"
UP = WORK / "upload2"
DONE = STATE / "uploaded2.txt"
LOG = WORK / "logs" / "upload2.log"
FIELDNAMES = ["id", "court", "case_type", "status", "final_stem", "dest_dir", "method", "note", "timestamp"]
BANAN_PDF_ID = "1hqUh0Mh2bh92zNeoROEMTwlSKIp9BPLT"
RCLONE = ["rclone", "move", str(UP), "gdrive:", "--drive-root-folder-id", BANAN_PDF_ID,
          "--no-traverse", "--transfers", "8", "--checkers", "8", "--retries", "5", "--low-level-retries", "10",
          "--log-file", str(WORK / "logs" / "rclone2.log"), "--log-level", "NOTICE"]


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def data2_records():
    """id -> (court.json, bản ghi có pdf_path) của mọi bản ghi đợt 2 đã tải PDF."""
    out = {}
    for rf in (WORK / "data2").glob("*/*/*/records_full.jsonl"):
        cj = rf.parent / "court.json"
        court = json.loads(cj.read_text(encoding="utf-8")) if cj.exists() else {}
        with rf.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("id"):
                    out[rec["id"]] = (court, rec)
    return out


def named_rows(ids):
    """Các dòng MacBook đã tạo MD (OK/THIEU) cho bản ghi đợt 2; dòng sau ghi đè dòng trước."""
    rows = {}
    p = STATE / "processed_mac.csv"
    if not p.exists():
        return rows
    with p.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, fieldnames=FIELDNAMES):
            if r.get("id") in ids and r.get("status") in ("OK", "THIEU") and r.get("final_stem") and r.get("dest_dir"):
                rows[r["id"]] = r
    return rows


def read_set(p):
    return set(p.read_text(encoding="utf-8").split()) if p.exists() else set()


def one_pass():
    recs = data2_records()
    rows = named_rows(recs)
    done = read_set(DONE)
    staged_f = STATE / "upload2_staged.tsv"
    staged = {}
    if staged_f.exists():
        for line in staged_f.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                staged[parts[0]] = (parts[1], parts[2])
    # 1) Đưa bản ghi mới có tên vào upload2/
    new = 0
    for rid, r in rows.items():
        if rid in done or rid in staged:
            continue
        src = recs[rid][1].get("pdf_path")
        if not src or not os.path.exists(src):
            continue
        dst = UP / r["dest_dir"] / f"{r['final_stem']}.pdf"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink()
        os.link(src, dst)
        staged[rid] = (str(dst), src)
        new += 1
    if new:
        staged_f.write_text("".join(f"{k}\t{a}\t{b}\n" for k, (a, b) in staged.items()), encoding="utf-8")
    if not staged:
        return 0, 0
    # 2) Đẩy lên Drive
    rc = subprocess.run(RCLONE).returncode
    # 3) File đã rời upload2/ là đã lên Drive: ghi nhận, xóa PDF gốc
    moved, left = [], {}
    for rid, (dst, src) in staged.items():
        if os.path.exists(dst):
            left[rid] = (dst, src)
        else:
            moved.append(rid)
            try:
                os.unlink(src)
            except FileNotFoundError:
                pass
    if moved:
        with DONE.open("a", encoding="utf-8") as f:
            f.write("".join(m + "\n" for m in moved))
    staged_f.write_text("".join(f"{k}\t{a}\t{b}\n" for k, (a, b) in left.items()), encoding="utf-8")
    for d in sorted(UP.rglob("*"), reverse=True):  # dọn thư mục rỗng
        if d.is_dir():
            try:
                d.rmdir()
            except OSError:
                pass
    if rc != 0:
        log(f"rclone trả mã {rc}; còn {len(left)} file chờ đẩy lại")
    return len(moved), len(left)


def status():
    recs = data2_records()
    rows = named_rows(recs)
    done = read_set(DONE)
    listed = defaultdict(int)
    for rl in (WORK / "data2").glob("*/*/*/records.jsonl"):
        cj = rl.parent / "court.json"
        name = json.loads(cj.read_text(encoding="utf-8")).get("ma_noi", rl.parent.parent.name) if cj.exists() else "?"
        with rl.open(encoding="utf-8") as f:
            listed[name] += sum(1 for line in f if line.strip())
    got, named, up = defaultdict(int), defaultdict(int), defaultdict(int)
    for rid, (court, rec) in recs.items():
        k = court.get("ma_noi", "?")
        got[k] += 1
        named[k] += rid in rows
        up[k] += rid in done
    courts = {}
    cl = WORK / "count_lower.json"
    if cl.exists():
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import lower_courts  # noqa: E402
        courts = {c["ma_noi"]: c["total"] for c in lower_courts.load(cl, ["tp-hcm", "ha-noi", "da-nang"])}
    keys = sorted(set(listed) | set(got), key=lambda k: -courts.get(k, 0))
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    out = ["# Tiến độ đợt 2 — TAND cấp huyện / khu vực", "", f"Cập nhật lúc: **{now}**", ""]
    if (WORK / "DOWNLOAD2_DONE").exists():
        out += ["Trạng thái: đã tải xong danh sách và PDF; đang tạo MD / đẩy PDF nốt.", ""]
    out += ["| Tòa (mã Nơi) | Trên cổng | Đã lấy danh sách | Đã tải PDF | Đã tạo MD | PDF đã lên Drive |",
            "|---|---:|---:|---:|---:|---:|"]
    t = [0] * 5
    for k in keys:
        v = [courts.get(k, 0), listed[k], got[k], named[k], up[k]]
        t = [a + b for a, b in zip(t, v)]
        out.append(f"| {k} | " + " | ".join(f"{x:,}".replace(",", ".") for x in v) + " |")
    out.append("| **Tổng** | " + " | ".join(f"**{x:,}**".replace(",", ".") for x in t) + " |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--every", type=int, default=120)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        print(status())
        return
    UP.mkdir(parents=True, exist_ok=True)
    last_report = 0
    while True:
        try:
            moved, left = one_pass()
            if moved or left:
                log(f"đã đẩy {moved} PDF lên BANAN PDF; còn chờ {left}")
            if time.time() - last_report >= 1800:
                rep = WORK / "TIEN_DO_DOT2.md"
                rep.write_text(status(), encoding="utf-8")
                subprocess.run(["rclone", "copyto", str(rep), "gdrive:_TIEN_DO_DOT2.md",
                                "--drive-root-folder-id", BANAN_PDF_ID, "--log-level", "ERROR"])
                last_report = time.time()
        except Exception as e:  # noqa: BLE001
            log(f"LỖI: {e}")
        if not a.loop:
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
