#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chạy trên MacBook: tạo MD cho một lô PDF thô kéo về từ VPS (vps/outbox_raw.py), ghi theo cấu trúc mới.

  MD : <md-root>/<THÀNH PHỐ>/CAP TINH/<NN LOẠI VỤ VIỆC>/<tên>.md      (md-root = .../000 - OBSIDIAN/MDBANAN)
  PDF: <pdf-root>/<THÀNH PHỐ>/CAP TINH/<NN LOẠI VỤ VIỆC>/<tên>.pdf    (pdf-root = .../My Drive/BANAN PDF)
  Không đọc được số/ngày → thư mục con "_CHUA DAT TEN".

Mỗi MD mở đầu bằng khối YAML (mac/frontmatter.py). Kết quả từng bản ghi ghi vào
<state-dir>/processed_mac.csv và <inbox>/_done.csv (để gửi lại VPS tính tiến độ).
Tương thích Python 3.9 (python3 có sẵn trên macOS).
"""
import argparse
import csv
import json
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "vps"))
sys.path.insert(0, str(HERE))
import process as P  # noqa: E402  (vps/process.py: đặt tên, trích văn bản/OCR)
import glob  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import frontmatter as FM  # noqa: E402

LEVEL_DIR = {"tinh": "CAP TINH", "huyen": "CAP HUYEN - KHU VUC", "khu-vuc": "CAP HUYEN - KHU VUC"}
CASE_LABEL = {
    "dan-su": "Dân sự", "hinh-su": "Hình sự", "kinh-doanh-thuong-mai": "Kinh doanh thương mại",
    "hon-nhan-gia-dinh": "Hôn nhân và gia đình", "lao-dong": "Lao động", "pha-san": "Phá sản",
    "hanh-chinh": "Hành chính", "xu-ly-hanh-chinh": "Xử lý hành chính",
}


def _ocr_pages(pdf_path, pages, tmpdir):
    out = []
    for pg in pages:
        base = os.path.join(tmpdir, f"p{pg}")
        subprocess.run(["pdftoppm", "-f", str(pg), "-l", str(pg), "-r", "200", "-png", pdf_path, base],
                       capture_output=True, timeout=300, check=False)
        for png in sorted(glob.glob(base + "*.png")):
            r = subprocess.run(["tesseract", png, "stdout", "-l", "vie", "--psm", "4"], capture_output=True,
                               text=True, timeout=180, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
            out.append((pg, r.stdout or ""))
    return out


def extract(pdf_path, partial=True):
    """Trả về (văn bản, phương pháp, số trang). PDF có lớp chữ: lấy toàn văn (NATIVE).
    PDF ảnh scan, partial=True và > 3 trang: chỉ OCR trang 1, 2 và trang cuối (OCR_MOT_PHAN);
    phần còn lại OCR sau bằng mac/ocr_full.py."""
    try:
        t = subprocess.run(["pdftotext", "-layout", pdf_path, "-"], capture_output=True, text=True, timeout=120).stdout or ""
    except Exception:  # noqa: BLE001
        t = ""
    npages = 1
    try:
        info = subprocess.run(["pdfinfo", pdf_path], capture_output=True, text=True, timeout=30).stdout or ""
        for line in info.splitlines():
            if line.startswith("Pages:"):
                npages = int(line.split(":")[1].strip())
    except Exception:  # noqa: BLE001
        pass
    if len(t.strip()) >= 60:
        return t, "NATIVE", npages
    tmpdir = tempfile.mkdtemp(prefix="ocr_")
    try:
        if partial and npages > 3:
            pages, method = [1, 2, npages], "OCR_MOT_PHAN"
        else:
            pages, method = list(range(1, min(npages, 80) + 1)), "OCR"
        res = _ocr_pages(pdf_path, pages, tmpdir)
        parts = []
        for i, (pg, txt) in enumerate(res):
            if method == "OCR_MOT_PHAN" and pg == npages and npages > 3:
                parts.append(f"[… trang 3–{npages - 1} chưa OCR, xem PDF gốc …]")
            parts.append(txt)
        return "\n\n".join(parts), method, npages
    except Exception as e:  # noqa: BLE001
        return "", f"ERROR:{e}", npages
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", required=True)
    ap.add_argument("--md-root", required=True)
    ap.add_argument("--pdf-root", required=True)
    ap.add_argument("--pdf-label", default="BANAN PDF", help="Tên thư mục PDF ghi vào khối thông tin")
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) - 1))
    ap.add_argument("--full-ocr", action="store_true", help="OCR toàn bộ các trang ngay (mặc định: OCR một phần)")
    a = ap.parse_args()

    inbox = Path(a.inbox)
    recs = []
    with (inbox / "records.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                recs.append(json.loads(line))
    done_csv = inbox / "_done.csv"
    already = set()
    if done_csv.exists():
        with done_csv.open(encoding="utf-8") as f:
            already = {r["id"] for r in csv.DictReader(f)}
    todo = [r for r in recs if r["id"] not in already and (inbox / r["pdf_rel"]).exists()]

    os.makedirs(a.state_dir, exist_ok=True)
    state_csv = Path(a.state_dir) / "processed_mac.csv"
    stats = {"ok": 0, "thieu": 0, "loi": 0, "ocr": 0}
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(extract, str(inbox / r["pdf_rel"]), not a.full_ocr): r for r in todo}
        for fut in as_completed(futs):
            rec = futs[fut]
            try:
                text, method, npages = fut.result()
            except Exception as e:  # noqa: BLE001
                text, method, npages = "", f"ERROR:{e}", 0
            row = write_one(a, inbox, rec, text, method, stats, npages)
            for path, header in ((state_csv, not state_csv.exists()), (done_csv, not done_csv.exists())):
                with open(path, "a", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=P.FIELDNAMES)
                    if header:
                        w.writeheader()
                    w.writerow(row)
    print(f"XONG lô {inbox.name}: {len(todo)} bản ghi | OK={stats['ok']} thiếu số/ngày={stats['thieu']} "
          f"lỗi={stats['loi']} dùng OCR={stats['ocr']}")
    return 0 if stats["loi"] == 0 else 1


def write_one(a, inbox, rec, text, method, stats, npages=0):
    court, case_type, rid = rec["court"], rec["case_type"], rec["id"]
    level = rec.get("cap", "tinh")
    if method.startswith("OCR"):
        stats["ocr"] += 1
    rel = Path(P.COURT_DIR[court]) / LEVEL_DIR[level] / P.CASE_TYPE_DIR[case_type]
    stem = P.build_stem(rec, court, case_type)
    thieu = stem is None
    if thieu:
        stem = f"{rid} - CHUA_XAC_DINH"
        rel = rel / "_CHUA DAT TEN"
    md_dir, pdf_dir = Path(a.md_root) / rel, Path(a.pdf_root) / rel
    final, n = stem, 2
    while (md_dir / f"{final}.md").exists() or (pdf_dir / f"{final}.pdf").exists():
        final = f"{stem} (bản {n})"
        n += 1

    nguoi = FM.tach_nguoi_tien_hanh_to_tung(text) if text else {"tham_phan": [], "thu_ky": [], "kiem_sat_vien": []}
    fields = {
        "toa": rec.get("toa_an_xet_xu") or P.COURT_LABEL[court],
        "cap": level,
        "loai_vu_viec": CASE_LABEL.get(case_type, case_type),
        "so": FM.so_hieu(rec.get("so_ngay_toa")),
        "ngay": FM.ngay_iso(rec.get("so_ngay_toa")),
        "so_ngay_toa": rec.get("so_ngay_toa", ""),
        "loai_van_ban": rec.get("loai_van_ban", ""),
        "cap_xet_xu": rec.get("cap_xet_xu", ""),
        "quan_he_phap_luat": rec.get("quan_he_phap_luat", ""),
        "tham_phan": nguoi["tham_phan"],
        "thu_ky": nguoi["thu_ky"],
        "kiem_sat_vien": nguoi["kiem_sat_vien"],
        "kiem_tra_ten": method.startswith("OCR"),
        "ocr_mot_phan": method == "OCR_MOT_PHAN",
        "so_trang": npages,
        "ap_dung_an_le": rec.get("ap_dung_an_le", ""),
        "dinh_chinh": rec.get("dinh_chinh", ""),
        "ma_cong": rid,
        "nguon": rec.get("url_chi_tiet", ""),
        "pdf_goc": rec.get("pdf_url", ""),
        "pdf": str(Path(a.pdf_label) / rel / f"{final}.pdf"),
        "trich_xuat": method,
        "ngay_tai": datetime.now().strftime("%Y-%m-%d"),
    }
    body = text or "(Không trích xuất được nội dung - cần kiểm tra lại file PDF gốc.)"
    status, note = ("THIEU" if thieu else "OK"), ""
    try:
        md_dir.mkdir(parents=True, exist_ok=True)
        pdf_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(inbox / rec["pdf_rel"]), str(pdf_dir / f"{final}.pdf"))
        tmp = md_dir / f".{final}.md.tmp"
        tmp.write_text(FM.build(fields) + f"\n# {final}\n\n" + body, encoding="utf-8")
        os.replace(tmp, md_dir / f"{final}.md")
        if method.startswith("ERROR") or not text:
            note = "khong trich xuat duoc van ban"
        stats["thieu" if thieu else "ok"] += 1
    except Exception as e:  # noqa: BLE001
        status, note = "LOI", str(e)
        stats["loi"] += 1
    return {"id": rid, "court": court, "case_type": case_type, "status": status, "final_stem": final,
            "dest_dir": str(rel), "method": method, "note": note,
            "timestamp": datetime.now().isoformat(timespec="seconds")}


if __name__ == "__main__":
    sys.exit(main())
