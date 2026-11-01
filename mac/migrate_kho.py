#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dọn kho bản án sang cấu trúc mới (chạy trên MacBook, SAU KHI Google Drive đã chuyển sang chế độ Stream).

Phần A — TAND cấp tỉnh đã xử lý theo cách cũ (CONGBOBANAN/TAND CAP TINH/<TP>/<LOẠI>/{PDF,MD,CHUA DAT TEN}):
  MD  → MDBANAN/<TP>/CAP TINH/<LOẠI>/  (đổi phần đầu sang khối YAML, tách Thẩm phán/Thư ký/KSV)
  PDF → BANAN PDF/<TP>/CAP TINH/<LOẠI>/
  Bản án đã có trong MDBANAN (cùng mã cổng) → chuyển sang BANAN PDF/_CHO PHAN LOAI/_TRUNG_LAP_CAP_TINH/.
Phần B — TAND tối cao, cấp cao và các thư mục cũ khác trong CONGBOBANAN:
  mọi PDF → BANAN PDF/_CHO PHAN LOAI/CONGBOBANAN/<đường dẫn cũ>  (MD giữ nguyên chờ phân loại)
  --xoa-docx: xoá mọi DOCX (vào Thùng rác Google Drive 30 ngày).

Mặc định chỉ chạy thử và báo số liệu; thêm --thuc-hien để làm thật. Nhật ký: ~/toaan-work/migrate_log.csv
"""
import argparse
import csv
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "vps"))
sys.path.insert(0, str(HERE))
import process as P  # noqa: E402
import frontmatter as FM  # noqa: E402
from process_inbox import CASE_LABEL  # noqa: E402

GD = Path.home() / "My Drive"
OLD = GD / "000 - OBSIDIAN" / "CONGBOBANAN"
MDB = GD / "000 - OBSIDIAN" / "MDBANAN"
PDFR = GD / "BANAN PDF"
PARK = PDFR / "_CHO PHAN LOAI"
LOG = Path.home() / "toaan-work" / "migrate_log.csv"
CITY_KEY = {v: k for k, v in P.COURT_DIR.items()}
CASE_KEY = {v: k for k, v in P.CASE_TYPE_DIR.items()}
HEADER_KEYS = {"Số/ngày": "so_ngay_toa", "Loại văn bản": "loai_van_ban", "Cấp xét xử": "cap_xet_xu",
               "Quan hệ pháp luật": "quan_he_phap_luat", "Tòa án": "toa", "Áp dụng án lệ": "ap_dung_an_le",
               "Đính chính": "dinh_chinh", "ID cổng thông tin": "ma_cong",
               "Nguồn (trang chi tiết cổng thông tin)": "nguon", "Link tải PDF gốc": "pdf_goc",
               "Ngày tải về": "ngay_tai", "Phương pháp trích xuất văn bản": "trich_xuat"}


def log(w, action, src, dst, note=""):
    w.writerow([datetime.now().isoformat(timespec="seconds"), action, str(src), str(dst), note])


def existing_ids():
    ids = set()
    for dp, _, fns in os.walk(MDB):
        for fn in fns:
            if fn.endswith(".md") and not fn.startswith((".", "_")):
                with open(os.path.join(dp, fn), encoding="utf-8", errors="ignore") as f:
                    for _ in range(25):
                        line = f.readline()
                        if line.startswith("ma_cong:"):
                            ids.add(line.split(":", 1)[1].strip().strip('"'))
                            break
    return ids


def parse_old_md(path):
    t = path.read_text(encoding="utf-8", errors="ignore")
    head, sep, body = t.partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        m = re.match(r"- (.+?): ?(.*)$", line)
        if m and m.group(1) in HEADER_KEYS:
            meta[HEADER_KEYS[m.group(1)]] = m.group(2).strip()
    return meta, (body.lstrip("\n") if sep else t)


def unique(path):
    if not path.exists():
        return path
    n = 2
    while True:
        p = path.with_name(f"{path.stem} (bản {n}){path.suffix}")
        if not p.exists():
            return p
        n += 1


def part_a(do, w, stats):
    src_root = OLD / "TAND CAP TINH"
    have = existing_ids()
    print(f"MDBANAN hiện có {len(have):,} mã cổng".replace(",", "."))
    for city_dir in sorted(p for p in src_root.iterdir() if p.is_dir() and p.name in CITY_KEY):
        court = CITY_KEY[city_dir.name]
        for case_dir in sorted(p for p in city_dir.iterdir() if p.is_dir() and p.name in CASE_KEY):
            case_type = CASE_KEY[case_dir.name]
            for sub in ("MD", "CHUA DAT TEN"):
                d = case_dir / sub
                if not d.is_dir():
                    continue
                for md in sorted(d.glob("*.md")):
                    meta, body = parse_old_md(md)
                    pdf_old = md.with_suffix(".pdf")
                    if sub == "MD":
                        pdf_old = case_dir / "PDF" / (md.stem + ".pdf")
                    rid = meta.get("ma_cong", "")
                    rel = Path(city_dir.name) / "CAP TINH" / case_dir.name / ("_CHUA DAT TEN" if sub != "MD" else "")
                    if rid and rid in have:
                        stats["trung"] += 1
                        dup = PARK / "_TRUNG_LAP_CAP_TINH" / rel
                        if do:
                            dup.mkdir(parents=True, exist_ok=True)
                            for f in (md, pdf_old):
                                if f.exists():
                                    shutil.move(str(f), str(unique(dup / f.name)))
                                    log(w, "trung_lap", f, dup)
                        continue
                    method = meta.get("trich_xuat", "")
                    nguoi = FM.tach_nguoi_tien_hanh_to_tung(body)
                    fields = {
                        "toa": meta.get("toa") or P.COURT_LABEL[court], "cap": "tinh",
                        "loai_vu_viec": CASE_LABEL.get(case_type, case_type),
                        "so": FM.so_hieu(meta.get("so_ngay_toa")), "ngay": FM.ngay_iso(meta.get("so_ngay_toa")),
                        "so_ngay_toa": meta.get("so_ngay_toa", ""), "loai_van_ban": meta.get("loai_van_ban", ""),
                        "cap_xet_xu": meta.get("cap_xet_xu", ""), "quan_he_phap_luat": meta.get("quan_he_phap_luat", ""),
                        "tham_phan": nguoi["tham_phan"], "thu_ky": nguoi["thu_ky"],
                        "kiem_sat_vien": nguoi["kiem_sat_vien"], "kiem_tra_ten": method.startswith("OCR"),
                        "ocr_mot_phan": False, "so_trang": 0, "ap_dung_an_le": meta.get("ap_dung_an_le", ""),
                        "dinh_chinh": meta.get("dinh_chinh", ""), "ma_cong": rid, "nguon": meta.get("nguon", ""),
                        "pdf_goc": meta.get("pdf_goc", ""),
                        "pdf": str(Path("BANAN PDF") / rel / (md.stem + ".pdf")),
                        "trich_xuat": method, "ngay_tai": meta.get("ngay_tai", ""),
                    }
                    md_new = unique(MDB / rel / md.name)
                    pdf_new = PDFR / rel / (md_new.stem + ".pdf")
                    fields["pdf"] = str(Path("BANAN PDF") / rel / pdf_new.name)
                    stats["chuyen"] += 1
                    if not pdf_old.exists():
                        stats["thieu_pdf"] += 1
                    if do:
                        md_new.parent.mkdir(parents=True, exist_ok=True)
                        pdf_new.parent.mkdir(parents=True, exist_ok=True)
                        if pdf_old.exists():
                            shutil.move(str(pdf_old), str(pdf_new))
                            log(w, "pdf", pdf_old, pdf_new)
                        tmp = md_new.with_name("." + md_new.name + ".tmp")
                        tmp.write_text(FM.build(fields) + f"\n# {md_new.stem}\n\n" + body, encoding="utf-8")
                        os.replace(tmp, md_new)
                        md.unlink()
                        log(w, "md", md, md_new)
                        have.add(rid)


def part_b(do, xoa_docx, w, stats):
    for dp, dns, fns in os.walk(OLD):
        rel_dp = Path(dp).relative_to(OLD)
        if rel_dp.parts[:1] in (("TAND CAP TINH",), ("_INDEX",)):
            dns[:] = []
            continue
        for fn in fns:
            src = Path(dp) / fn
            low = fn.lower()
            if low.endswith(".pdf"):
                stats["pdf_cho"] += 1
                stats["pdf_cho_gb"] += src.stat().st_size / 1e9
                if do:
                    dst = PARK / "CONGBOBANAN" / rel_dp / fn
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(unique(dst)))
                    log(w, "pdf_cho_phan_loai", src, dst)
            elif low.endswith(".docx") and xoa_docx:
                stats["docx"] += 1
                if do:
                    src.unlink()
                    log(w, "xoa_docx", src, "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thuc-hien", action="store_true", help="Làm thật (mặc định: chạy thử)")
    ap.add_argument("--xoa-docx", action="store_true")
    ap.add_argument("--chi-phan", choices=["A", "B"], help="Chỉ chạy phần A hoặc B")
    ap.add_argument("--cho-phep-mirror", action="store_true")
    a = ap.parse_args()
    real = os.path.realpath(GD)
    if a.thuc_hien and "CloudStorage" not in real and not a.cho_phep_mirror:
        sys.exit(f"~/My Drive đang trỏ tới {real} — có vẻ Google Drive vẫn ở chế độ Mirror. "
                 "Đổi sang Stream và tạo liên kết ~/My Drive trước.")
    for p in (OLD, MDB):
        if not p.is_dir():
            sys.exit(f"Không thấy {p}")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stats = {"chuyen": 0, "trung": 0, "thieu_pdf": 0, "pdf_cho": 0, "pdf_cho_gb": 0.0, "docx": 0}
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if a.chi_phan in (None, "A"):
            part_a(a.thuc_hien, w, stats)
        if a.chi_phan in (None, "B"):
            part_b(a.thuc_hien, a.xoa_docx, w, stats)
    mode = "ĐÃ THỰC HIỆN" if a.thuc_hien else "CHẠY THỬ (chưa đổi gì)"
    print(f"\n{mode}\n"
          f"A. Cấp tỉnh: chuyển sang cấu trúc mới {stats['chuyen']:,} bản án "
          f"(thiếu PDF {stats['thieu_pdf']}); trùng với MDBANAN {stats['trung']:,}\n"
          f"B. PDF tối cao/cấp cao/khác sang _CHO PHAN LOAI: {stats['pdf_cho']:,} file "
          f"({stats['pdf_cho_gb']:.1f} GB); DOCX xoá: {stats['docx']:,}".replace(",", "."))


if __name__ == "__main__":
    main()
