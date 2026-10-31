#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Đặt lại tên cho các bản án đã lên Drive trong thư mục "CHUA DAT TEN" mà nay đọc được số/ngày
(sau khi sửa SO_NGAY_RE trong process.py). Đổi tên trực tiếp trên Drive bằng rclone moveto
và cập nhật state CSV. Chạy một lần (process_loop.sh gọi khi chưa có dấu "names_fixed_v1")."""
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import process as P  # noqa: E402

WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
DEST = "gdrive:" + P.ROOT_DIR


def main():
    st = WORK / "state" / "processed.csv"
    if not st.exists():
        return
    recs = {}
    for rf in (WORK / "data").glob("*/*/*/records_full.jsonl"):
        for line in rf.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("id"):
                recs[r["id"]] = r
    rows = list(csv.DictReader(st.open(encoding="utf-8-sig")))
    used = {(r["dest_dir"], r["final_stem"]) for r in rows}
    fixed = 0
    for row in rows:
        if row["status"] != "THIEU" or row["id"] not in recs:
            continue
        stem = P.build_stem(recs[row["id"]], row["court"], row["case_type"])
        if not stem:
            continue
        final, n = stem, 2
        while (row["dest_dir"], final) in used:
            final = f"{stem} (bản {n})"
            n += 1
        ok = True
        for ext, sub in (("pdf", "PDF"), ("md", "MD")):
            src = f"{DEST}/{row['dest_dir']}/CHUA DAT TEN/{row['final_stem']}.{ext}"
            dst = f"{DEST}/{row['dest_dir']}/{sub}/{final}.{ext}"
            if subprocess.run(["rclone", "moveto", src, dst, "--retries", "3"], capture_output=True).returncode:
                ok = False
        if ok:
            used.add((row["dest_dir"], final))
            row.update(status="OK", final_stem=final, note="doi ten lai")
            fixed += 1
    tmp = st.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=P.FIELDNAMES)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(st)
    print(f"Đã đặt lại tên {fixed} bản án trong CHUA DAT TEN")


if __name__ == "__main__":
    main()
