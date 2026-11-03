#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In mẫu các bản ghi đợt 2 bị xếp loại KHAC / giai đoạn KHAC / LỖI kèm trường gốc từ cổng (để sửa quy tắc đặt tên)."""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fix_names2 as F  # noqa: E402

recs = F.load_records()
rows = list(csv.DictReader(F.X.STATE_CSV.open(encoding="utf-8-sig")))
kinds = {"LOI": [], "KHAC": [], "GD_KHAC": []}
for r in rows:
    if r["status"] == "LOI":
        kinds["LOI"].append(r)
    elif "-KHAC-" in r["final_stem"]:
        kinds["KHAC"].append(r)
    if " - KHAC-" in r["final_stem"]:
        kinds["GD_KHAC"].append(r)
ok_ids = {r["id"] for r in rows if r["status"] != "LOI"}
twin = sum(1 for r in kinds["LOI"] if r["id"] in ok_ids)
pdf_left = sum(1 for r in kinds["LOI"] if (recs.get(r["id"], (None, {}))[1].get("pdf_path") or "") and
               Path(recs[r["id"]][1]["pdf_path"]).exists())
print(f"LỖI: {twin} dòng trùng một bản đã xử lý xong (vô hại) | {pdf_left} còn PDF trên VPS (sẽ làm lại)")
print(f"Tổng {len(rows)} | LỖI {len(kinds['LOI'])} | loại KHAC {len(kinds['KHAC'])} | giai đoạn KHAC {len(kinds['GD_KHAC'])}")
keys = ("so_ngay_toa", "cap_xet_xu", "loai_vu_viec", "loai_van_ban", "quan_he_phap_luat", "thong_tin_vu_viec")
for name, lst in kinds.items():
    print(f"\n== {name} (mẫu {min(len(lst), 8)}) ==")
    for r in lst[:8]:
        rec = recs.get(r["id"], (None, {}))[1]
        print(f"- {r['final_stem'][:90]}  [{r['note'][:80]}]")
        print("   " + json.dumps({k: rec.get(k) for k in keys}, ensure_ascii=False)[:400])
