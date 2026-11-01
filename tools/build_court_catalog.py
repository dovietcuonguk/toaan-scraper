#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lập danh mục toàn bộ Tòa án trên congbobanan (mọi cấp) để tra cứu nhanh.

Đầu vào : probe_levels.json (tools/probe_levels.py), count_lower.json (tools/count_lower.py, tùy chọn),
          vps/expected_counts.json (số bản án cấp tỉnh của 3 thành phố).
Đầu ra  : <out-dir>/_DANH MUC TOA AN.md   (đọc trong Obsidian)
          <out-dir>/_danh_muc_toa_an.csv  (mở bằng Excel/Numbers; script dùng chung)
          <out-dir>/_danh_muc_toa_an.json
Mỗi Tòa: mã cổng, tên, cấp, loại, Tòa cấp trên, tỉnh/thành, mã "Nơi" trong tên file, thư mục lưu trong kho,
thuộc phạm vi kho hay không, số bản án đã công bố (nếu đã đếm), tên không dấu để tìm nhanh.

  python3 tools/build_court_catalog.py --probe probe_levels.json --count count_lower.json --out-dir <MDBANAN>
"""
import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEVEL_NAME = {"TW": "TAND tối cao", "CW": "TAND cấp cao", "T": "TAND cấp tỉnh", "H": "TAND cấp huyện / khu vực"}
CITY = {  # tỉnh/thành → (mã Nơi, thư mục trong kho, khóa trong expected_counts)
    "Hồ Chí Minh": ("HCM", "TP HO CHI MINH", "tp-hcm"),
    "Hà Nội": ("HN", "HA NOI", "ha-noi"),
    "Đà Nẵng": ("ĐN", "DA NANG", "da-nang"),
}
CC_DIR = {"Hà Nội": "Hà Nội", "Đà Nẵng": "Đà Nẵng", "Hồ Chí Minh": "TP HCM"}
IN_SCOPE_T = {"787", "784", "775"}


def khong_dau(s):
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).lower().strip()


def which_city(text):
    for k in CITY:
        if k.lower() in text.lower():
            return k
    return ""


def province_of(name):
    m = re.match(r"(?:TAND|Tòa án nhân dân)\s+(?:tỉnh|thành phố|TP\.?)\s*(.+)$", name.strip(), re.I)
    return m.group(1).strip() if m else name.strip()


def short_lower(name):
    n = name.strip()
    m = re.search(r"khu vực\s*(\d+)", n, re.I)
    if m:
        return f"KV{m.group(1)}"
    n = re.sub(r"^(TAND|Tòa án nhân dân)\s+", "", n)
    if re.match(r"(thành phố|TP\.)\s*", n, re.I):  # thành phố thuộc thành phố (vd TP. Thủ Đức)
        return "TP " + re.sub(r"^(thành phố|TP\.)\s*", "", n, flags=re.I).strip()
    n = re.sub(r"^(Q\.|huyện|thị xã|TX\.)\s*", "", n, flags=re.I)
    return n.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", required=True)
    ap.add_argument("--count", default="")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    probe = json.loads(Path(a.probe).read_text(encoding="utf-8"))
    counts = json.loads(Path(a.count).read_text(encoding="utf-8")) if a.count and Path(a.count).exists() else {}
    exp = json.loads((REPO / "vps" / "expected_counts.json").read_text(encoding="utf-8"))

    rows = []
    for lv, info in probe["courts"].items():
        for value, text in info["options"]:
            if not value:
                continue
            m = re.match(r"^(.*?)\s*\((.+?)\s*\)\s*$", text)
            name, parent = (m.group(1).strip(), m.group(2).strip()) if m else (text.strip(), "")
            quan_su = "quân sự" in text.lower() or "quân khu" in text.lower() or "TAQS" in text or "Hải Quân" in text
            r = {"ma_cong": value, "ten": name, "cap": lv, "cap_ten": LEVEL_NAME.get(lv, lv), "toa_cap_tren": parent,
                 "loai": "", "tinh_thanh": "", "ma_noi": "", "thu_muc": "", "pham_vi_kho": False, "so_ban_an": ""}
            if lv == "TW":
                if quan_su:
                    r["loai"] = "quân sự"
                elif "Phúc thẩm" in name:
                    c = which_city(name)
                    r.update(loai="Tòa Phúc thẩm TANDTC (trước khi có TAND cấp cao)", tinh_thanh=c,
                             ma_noi=f"TPT-{CITY[c][0]}" if c else "TPT", pham_vi_kho=True,
                             thu_muc=f"TOI CAO/TOA PHUC THAM/{CC_DIR.get(c, c)}")
                else:
                    r.update(loai="TAND tối cao", ma_noi="TC", thu_muc="TOI CAO", pham_vi_kho=True)
            elif lv == "CW":
                c = which_city(name)
                r.update(loai="TAND cấp cao", tinh_thanh=c, ma_noi=f"CC-{CITY[c][0]}" if c else "CC",
                         thu_muc=f"CAP CAO/{CC_DIR.get(c, c)}", pham_vi_kho=True)
            elif lv == "T":
                prov = province_of(name)
                r.update(loai="quân sự" if quan_su else "TAND cấp tỉnh", tinh_thanh=prov)
                if value in IN_SCOPE_T:
                    c = which_city(name)
                    code, folder, key = CITY[c]
                    r.update(ma_noi=code, thu_muc=f"{folder}/CAP TINH", pham_vi_kho=True,
                             so_ban_an=sum(v for v in exp[key].values()))
                else:
                    r["ma_noi"] = prov
            else:  # H
                parent_prov = province_of(parent) if parent else ""
                kind = "quân sự" if quan_su else ("TAND khu vực" if "khu vực" in name.lower() else "TAND cấp huyện (đến 30/6/2025)")
                r.update(loai=kind, tinh_thanh=parent_prov)
                c = which_city(parent)
                if c and not quan_su:
                    code, folder, _ = CITY[c]
                    r.update(ma_noi=f"{code}-{short_lower(name)}", thu_muc=f"{folder}/CAP HUYEN - KHU VUC", pham_vi_kho=True)
                elif not quan_su:
                    r["ma_noi"] = f"{parent_prov}-{short_lower(name)}"
                if value in counts and isinstance(counts[value].get("total"), int):
                    r["so_ban_an"] = counts[value]["total"]
            r["tim_nhanh"] = khong_dau(f"{name} {r['ma_noi']} {r['tinh_thanh']}")
            rows.append(r)

    order = {"TW": 0, "CW": 1, "T": 2, "H": 3}
    rows.sort(key=lambda r: (not r["pham_vi_kho"], order.get(r["cap"], 9), r["tinh_thanh"], r["loai"], khong_dau(r["ten"])))
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cols = ["ma_cong", "ten", "cap", "cap_ten", "loai", "toa_cap_tren", "tinh_thanh", "ma_noi", "thu_muc",
            "pham_vi_kho", "so_ban_an", "tim_nhanh"]
    with (out / "_danh_muc_toa_an.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    (out / "_danh_muc_toa_an.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    def vn(n):
        return f"{n:,}".replace(",", ".") if isinstance(n, int) else ""

    md = ["---", 'loai_ghi_chu: "danh-muc-toa-an"', f'so_toa: {len(rows)}', "---", "",
          "# Danh mục Tòa án trên Cổng công bố bản án (congbobanan.toaan.gov.vn)", "",
          f"Tổng cộng **{len(rows)} Tòa** (TAND tối cao, cấp cao, cấp tỉnh, cấp huyện/khu vực, kể cả Tòa án quân sự). "
          f"Trong phạm vi kho MDBANAN: **{sum(r['pham_vi_kho'] for r in rows)} Tòa**.", "",
          "- **Mã Nơi**: đoạn thứ hai trong tên file bản án (vd `20251120 - HCM-KV3 - ST-HS-2025-88 - ...`).",
          "- **Thư mục**: đường dẫn trong `MDBANAN/` (MD) và `BANAN PDF/` (PDF), sau đó là thư mục loại vụ việc.",
          "- **Mã cổng**: giá trị của Tòa trong ô chọn Tòa trên cổng; dùng cho script tải bản án.",
          "- Danh sách đầy đủ mọi Tòa (kể cả ngoài phạm vi kho): `_danh_muc_toa_an.csv`.", ""]
    sections = [
        ("TAND tối cao", lambda r: r["cap"] == "TW" and r["pham_vi_kho"]),
        ("TAND cấp cao", lambda r: r["cap"] == "CW"),
        ("TAND cấp tỉnh trong phạm vi kho", lambda r: r["cap"] == "T" and r["pham_vi_kho"]),
    ]
    for c in CITY:
        sections.append((f"TAND cấp huyện (đến 30/6/2025) — {c}",
                         lambda r, c=c: r["cap"] == "H" and r["pham_vi_kho"] and r["tinh_thanh"].endswith(c) and "huyện" in r["loai"]))
        sections.append((f"TAND khu vực (từ 01/7/2025) — {c}",
                         lambda r, c=c: r["cap"] == "H" and r["pham_vi_kho"] and r["tinh_thanh"].endswith(c) and "khu vực" in r["loai"]))
    for title, pred in sections:
        sel = [r for r in rows if pred(r)]
        if not sel:
            continue
        total = sum(r["so_ban_an"] for r in sel if isinstance(r["so_ban_an"], int))
        md += [f"## {title} ({len(sel)} Tòa" + (f"; {vn(total)} bản án" if total else "") + ")", "",
               "| Mã Nơi | Tòa án | Mã cổng | Thư mục | Số bản án |", "|---|---|---|---|---|"]
        md += [f"| {r['ma_noi']} | {r['ten']} | {r['ma_cong']} | {r['thu_muc']} | {vn(r['so_ban_an'])} |" for r in sel]
        md.append("")
    others = [r for r in rows if r["cap"] == "T" and not r["pham_vi_kho"]]
    md += [f"## TAND cấp tỉnh khác ({len(others)} Tòa, ngoài phạm vi kho)", "",
           "| Tòa án | Mã cổng |", "|---|---|"] + [f"| {r['ten']} | {r['ma_cong']} |" for r in others] + [""]
    (out / "_DANH MUC TOA AN.md").write_text("\n".join(md), encoding="utf-8")
    print(f"Đã ghi {len(rows)} Tòa vào {out}")


if __name__ == "__main__":
    main()
