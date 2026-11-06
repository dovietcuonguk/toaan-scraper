#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ghép chữ OCR (do vps/ocr2.py tạo) vào MD đang có trong MDBANAN — chạy trên MacBook.

python3 ocr_ghep.py <thư mục lô đã kéo về> <MDBANAN> <tệp chỉ mục ma_cong>
- Tìm MD theo đường dẫn ghi trong JSON; tên đã đổi thì tra chỉ mục ma_cong → đường dẫn (dựng một lần khi cần).
- Thay từng dấu "[… trang n: ảnh scan, chưa OCR — xem PDF gốc …]" bằng chữ OCR của trang n.
- YAML: trang_anh → [], can_ocr → false, trich_xuat → "NATIVE+OCR"; tham_phan/thu_ky/kiem_sat_vien chỉ
  điền khi đang rỗng. Ghi qua tệp tạm rồi đổi tên. PDF trên Drive không đụng tới.
- JSON ghép xong thì xóa; không tìm thấy MD thì chuyển vào <lô>/../_khong_thay để xem sau.
"""
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

MARK = "[… trang {}: ảnh scan, chưa OCR — xem PDF gốc …]"
LEVEL = "CAP HUYEN - KHU VUC"
MA_RE = re.compile(r'^ma_cong:\s*"?([^"\n]+)"?\s*$', re.M)


def build_index(root, cache):
    print("  Dựng chỉ mục ma_cong → MD (một lần, có thể 10–20 phút)...", flush=True)
    idx = {}
    for city in sorted(p for p in root.iterdir() if p.is_dir()):
        lv = city / LEVEL
        if not lv.is_dir():
            continue
        for md in lv.rglob("*.md"):
            if md.name.startswith("."):
                continue
            try:
                with md.open(encoding="utf-8") as f:
                    head = f.read(4000)
            except OSError:
                continue
            m = MA_RE.search(head)
            if m:
                idx[m.group(1).strip()] = str(md.relative_to(root))
    cache.write_text("".join(f"{k}\t{v}\n" for k, v in idx.items()), encoding="utf-8")
    print(f"  Chỉ mục: {len(idx):,} MD", flush=True)
    return idx


def load_index(cache):
    idx = {}
    if cache.exists():
        for line in cache.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("\t")
            if v:
                idx[k] = v
    return idx


def ma_cong(md):
    try:
        with md.open(encoding="utf-8") as f:
            m = MA_RE.search(f.read(4000))
        return m.group(1).strip() if m else None
    except OSError:
        return None


def merge(md, j):
    s = md.read_text(encoding="utf-8")
    if not s.startswith("---\n"):
        return False
    end = s.find("\n---\n", 4)
    if end < 0:
        return False
    head, body = s[: end + 5], s[end + 5:]
    for p, t in j["pages"].items():
        rep = t.strip() or f"[trang {p}: ảnh scan — OCR không đọc được chữ]"
        body = body.replace(MARK.format(p), rep)
    head = re.sub(r"^trang_anh:.*$", "trang_anh: []", head, flags=re.M)
    head = re.sub(r"^can_ocr:.*$", "can_ocr: false", head, flags=re.M)
    head = re.sub(r'^trich_xuat:\s*"NATIVE_MOT_PHAN"\s*$', 'trich_xuat: "NATIVE+OCR"', head, flags=re.M)
    for k in ("tham_phan", "thu_ky", "kiem_sat_vien"):
        if j.get(k):
            head = re.sub(rf"^{k}:\s*\[\]\s*$", f"{k}: {json.dumps(j[k], ensure_ascii=False)}", head, flags=re.M)
    new = head + body
    if new != s:
        tmp = md.with_name(f".{md.name}.ocrtmp")
        tmp.write_text(new, encoding="utf-8")
        os.replace(tmp, md)
    return True


def main():
    inbox, root, cache = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    lost = inbox / "_khong_thay"
    idx = None
    ok = miss = 0
    for jf in sorted(inbox.glob("ocr-*/*.json")):
        j = json.loads(jf.read_text(encoding="utf-8"))
        md = root / unicodedata.normalize("NFC", j["md"])
        if not md.exists() or ma_cong(md) != j["id"]:
            if idx is None:
                idx = load_index(cache)
            rel = idx.get(j["id"])
            if not rel or not (root / rel).exists():
                if not getattr(main, "rebuilt", False):
                    idx = build_index(root, cache)
                    main.rebuilt = True
                rel = idx.get(j["id"])
            md = root / rel if rel else None
        if md and md.exists() and merge(md, j):
            jf.unlink()
            ok += 1
        else:
            lost.mkdir(parents=True, exist_ok=True)
            os.replace(jf, lost / jf.name)
            miss += 1
    for d in inbox.glob("ocr-*"):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    print(f"  Ghép OCR: {ok:,} MD" + (f" · {miss} không tìm thấy MD (xem {lost})" if miss else ""), flush=True)


if __name__ == "__main__":
    main()
