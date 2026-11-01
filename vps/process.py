#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vps/process.py — Bước xử lý trên VPS cho bản án TAND cấp tỉnh (TP. Hồ Chí Minh, Hà Nội, Đà Nẵng).

Đọc các file records_full.jsonl (do scrape_toaan.py + fetch_pdfs.py tạo) trong
  <work>/data/<toa>/<loai-vu-viec>/<nhom>/records_full.jsonl
Với mỗi bản ghi đã có PDF và chưa xử lý (theo state CSV):
  1. Trích toàn văn: pdftotext; nếu không có lớp chữ thì OCR tesseract (tiếng Việt) từng trang.
  2. Đặt tên theo quy ước sẵn có của CONGBOBANAN:
       YYYYMMDD - <Nơi> - <Giai đoạn>-<Loại>-<Năm>-<Số> - <Quan hệ pháp luật>
  3. Ghi PDF + MD (và DOCX nếu bật --docx) vào thư mục chờ đẩy lên Drive:
       <staging>/TAND CAP TINH/<TOA>/<NN LOAI VU VIEC>/{PDF,MD,DOCX,CHUA DAT TEN}/
  4. Ghi state CSV để chạy lại nhiều lần không xử lý trùng.

Dựa trên banan_pipeline_process.py (bản chạy trên MacBook), giữ nguyên cách đặt tên và
phần đầu file MD để công cụ tra cứu cục bộ (banan_build_search_index.py) đọc được.
Trích văn bản chạy song song theo số nhân CPU.
"""
import argparse
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT_DIR = "TAND CAP TINH"
COURT_DIR = {"tp-hcm": "TP HO CHI MINH", "ha-noi": "HA NOI", "da-nang": "DA NANG"}
COURT_LOC = {"tp-hcm": "HCM", "ha-noi": "HN", "da-nang": "ĐN"}
COURT_LABEL = {"tp-hcm": "TAND TP. Hồ Chí Minh", "ha-noi": "TAND TP. Hà Nội", "da-nang": "TAND TP. Đà Nẵng"}

CASE_TYPE_DIR = {
    "dan-su": "01 DAN SU",
    "hinh-su": "02 HINH SU",
    "kinh-doanh-thuong-mai": "03 KINH DOANH THUONG MAI",
    "hon-nhan-gia-dinh": "04 HON NHAN GIA DINH",
    "lao-dong": "05 LAO DONG",
    "pha-san": "06 PHA SAN",
    "hanh-chinh": "07 HANH CHINH",
    "xu-ly-hanh-chinh": "08 XU LY HANH CHINH",
}
CASE_TYPE_CODE = {
    "dan-su": "DS", "hinh-su": "HS", "kinh-doanh-thuong-mai": "KDTM",
    "hon-nhan-gia-dinh": "HNGD", "lao-dong": "LD", "pha-san": "PS", "hanh-chinh": "HC",
    "xu-ly-hanh-chinh": "XLHC",
}
PHASE_CODE = [
    (re.compile(r"Gi[áa]m\s*đ[ốo]c\s*th[ẩa]m", re.I), "GDT"),
    (re.compile(r"T[áa]i\s*th[ẩa]m", re.I), "TT"),
    (re.compile(r"Ph[úu]c\s*th[ẩa]m", re.I), "PT"),
    (re.compile(r"S[ơo]\s*th[ẩa]m", re.I), "ST"),
]
# Cho phép số hiệu có khoảng trắng bên trong (vd "số 837 /2020/QĐST-DS ngày 24/06/2020")
SO_NGAY_RE = re.compile(r"s[ốo]\s*(.+?)\s*ng[àa]y\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})", re.I)
FIELDNAMES = ["id", "court", "case_type", "status", "final_stem", "dest_dir", "method", "note", "timestamp"]


def phase_code_of(cap_xet_xu):
    for pat, code in PHASE_CODE:
        if pat.search(cap_xet_xu or ""):
            return code
    return "KHAC"


def sanitize(s, maxlen=150):
    if not s:
        return "CHUA_XAC_DINH"
    s = s.replace("/", "-").replace("\\", "-")
    s = re.sub(r'[<>:"|?*\n\r\t]', "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:maxlen]


def build_stem(rec, court, case_type):
    m = SO_NGAY_RE.search(rec.get("so_ngay_toa") or "")
    if not m:
        return None
    so_raw, d, mo, y = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
    if not (1 <= d <= 31 and 1 <= mo <= 12 and 1900 <= y <= 2100):
        return None
    so_clean = re.sub(r"[^0-9A-Za-z]", "", so_raw)
    if not so_clean:
        return None
    ma = f"{phase_code_of(rec.get('cap_xet_xu'))}-{CASE_TYPE_CODE.get(case_type, 'KHAC')}-{y}-{so_clean}"
    tom_tat = sanitize(rec.get("quan_he_phap_luat") or rec.get("thong_tin_vu_viec") or "")
    return f"{y:04d}{mo:02d}{d:02d} - {COURT_LOC[court]} - {ma} - {tom_tat}"


def extract_text(pdf_path, max_pages=80):
    """Trả về (văn bản, phương pháp). Chạy trong tiến trình con."""
    try:
        out = subprocess.run(["pdftotext", "-layout", pdf_path, "-"], capture_output=True, text=True, timeout=120)
        text = out.stdout or ""
    except Exception:
        text = ""
    if len(text.strip()) >= 60:
        return text, "NATIVE"
    tmpdir = tempfile.mkdtemp(prefix="ocr_")
    try:
        info = subprocess.run(["pdfinfo", pdf_path], capture_output=True, text=True, timeout=30)
        npages = 1
        for line in (info.stdout or "").splitlines():
            if line.startswith("Pages:"):
                npages = int(line.split(":")[1].strip())
        npages = max(1, min(npages, max_pages))
        base = os.path.join(tmpdir, "p")
        subprocess.run(["pdftoppm", "-f", "1", "-l", str(npages), "-r", "200", "-png", pdf_path, base],
                       capture_output=True, timeout=600, check=False)
        pages = []
        for png in sorted(glob.glob(base + "*.png")):
            r = subprocess.run(["tesseract", png, "stdout", "-l", "vie", "--psm", "4"],
                               capture_output=True, text=True, timeout=180,
                               env={**os.environ, "OMP_THREAD_LIMIT": "1"})
            pages.append(r.stdout or "")
        return "\n\n".join(pages), "OCR"
    except Exception as e:  # noqa: BLE001
        return "", f"ERROR:{e}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def load_state(state_csv):
    done, used = set(), set()
    if os.path.exists(state_csv):
        with open(state_csv, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                done.add(row["id"])
                used.add((row["dest_dir"], row["final_stem"]))
    return done, used


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--staging-dir", required=True)
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--batch", type=int, default=200, help="Số bản ghi tối đa mỗi lần chạy")
    ap.add_argument("--docx", action="store_true", help="Tạo thêm file DOCX bằng pandoc")
    args = ap.parse_args()

    # Dọn thư mục OCR tạm bị bỏ lại (khi tiến trình OCR bị dừng đột ngột, ví dụ thiếu RAM)
    import time as _t
    for d in glob.glob(os.path.join(tempfile.gettempdir(), "ocr_*")):
        try:
            if _t.time() - os.path.getmtime(d) > 3600:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass
    # Chuyển PDF từ data sang staging cùng ổ đĩa không tốn thêm chỗ; chỉ cần chỗ cho MD và ảnh OCR tạm
    if shutil.disk_usage("/").free < 4e8:
        print("Ổ đĩa còn dưới 400 MB — tạm dừng xử lý, chờ đẩy file lên Drive giải phóng chỗ.")
        return

    os.makedirs(args.state_dir, exist_ok=True)
    state_csv = os.path.join(args.state_dir, "processed.csv")
    write_header = not os.path.exists(state_csv)
    done, used = load_state(state_csv)

    todo = []
    for rf in sorted(Path(args.data_dir).glob("*/*/*/records_full.jsonl")):
        court, case_type = rf.parts[-4], rf.parts[-3]
        if court not in COURT_DIR or case_type not in CASE_TYPE_DIR:
            continue
        with rf.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:  # dòng cuối đang được fetch_pdfs.py ghi dở
                    continue
                rid = rec.get("id")
                if not rid or rid in done:
                    continue
                if not rec.get("pdf_path") or not os.path.exists(rec["pdf_path"]):
                    continue
                todo.append((court, case_type, rec))
                done.add(rid)  # tránh trùng nếu cùng id xuất hiện ở 2 nhóm
                if len(todo) >= args.batch:
                    break
        if len(todo) >= args.batch:
            break
    if not todo:
        print("Không có bản ghi mới cần xử lý.")
        return

    stats = {"ok": 0, "thieu": 0, "loi": 0, "ocr": 0}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(extract_text, rec["pdf_path"]): (court, ct, rec) for court, ct, rec in todo}
        for fut in as_completed(futs):
            court, case_type, rec = futs[fut]
            rid = rec["id"]
            try:
                text, method = fut.result()
            except Exception as e:  # noqa: BLE001
                text, method = "", f"ERROR:{e}"
            if method == "OCR":
                stats["ocr"] += 1

            dest_root = Path(args.staging_dir) / ROOT_DIR / COURT_DIR[court] / CASE_TYPE_DIR[case_type]
            stem = build_stem(rec, court, case_type)
            thieu = stem is None
            if thieu:
                stem = f"{rid} - CHUA_XAC_DINH"
            sub_pdf, sub_md, sub_docx = (("CHUA DAT TEN",) * 3) if thieu else ("PDF", "MD", "DOCX")
            rel_dir = str(Path(COURT_DIR[court]) / CASE_TYPE_DIR[case_type])
            final_stem, n = stem, 2
            while (rel_dir, final_stem) in used:
                final_stem = f"{stem} (bản {n})"
                n += 1
            used.add((rel_dir, final_stem))

            header = [
                f"# {final_stem}", "",
                f"- Số/ngày: {rec.get('so_ngay_toa', '')}",
                f"- Loại văn bản: {rec.get('loai_van_ban', '')}",
                f"- Cấp xét xử: {rec.get('cap_xet_xu', '')}",
                f"- Quan hệ pháp luật: {rec.get('quan_he_phap_luat', '')}",
                f"- Loại vụ việc: {rec.get('loai_vu_viec', '')}",
                "- Cấp tòa: tinh",
                f"- Tòa án: {rec.get('toa_an_xet_xu') or COURT_LABEL[court]}",
                f"- Áp dụng án lệ: {rec.get('ap_dung_an_le', '')}",
                f"- Đính chính: {rec.get('dinh_chinh', '')}",
                f"- ID cổng thông tin: {rid}",
                f"- Nguồn (trang chi tiết cổng thông tin): {rec.get('url_chi_tiet', '')}",
                f"- Link tải PDF gốc: {rec.get('pdf_url', '')}",
                f"- Ngày tải về: {datetime.now().strftime('%Y-%m-%d')}",
                f"- Phương pháp trích xuất văn bản: {method}",
                "", "---", "",
            ]
            body = text or "(Không trích xuất được nội dung - cần kiểm tra lại file PDF gốc.)"
            status, note = ("THIEU" if thieu else "OK"), ""
            try:
                for sub in {sub_pdf, sub_md}:
                    (dest_root / sub).mkdir(parents=True, exist_ok=True)
                md_path = dest_root / sub_md / f"{final_stem}.md"
                tmp_md = md_path.with_name(md_path.name + ".tmp")  # ghi tạm rồi đổi tên: không ai lấy được file MD ghi dở
                tmp_md.write_text("\n".join(header) + body, encoding="utf-8")
                os.replace(tmp_md, md_path)
                if args.docx:
                    (dest_root / sub_docx).mkdir(parents=True, exist_ok=True)
                    subprocess.run(["pandoc", str(md_path), "-o", str(dest_root / sub_docx / f"{final_stem}.docx")],
                                   capture_output=True, timeout=120, check=False)
                shutil.move(rec["pdf_path"], dest_root / sub_pdf / f"{final_stem}.pdf")
                if method.startswith("ERROR") or not text:
                    note = "khong trich xuat duoc van ban"
                stats["thieu" if thieu else "ok"] += 1
            except Exception as e:  # noqa: BLE001
                status, note = "LOI", str(e)
                stats["loi"] += 1
            with open(state_csv, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=FIELDNAMES)
                if write_header:
                    w.writeheader()
                    write_header = False
                w.writerow({"id": rid, "court": court, "case_type": case_type, "status": status,
                            "final_stem": final_stem, "dest_dir": rel_dir, "method": method, "note": note,
                            "timestamp": datetime.now().isoformat(timespec="seconds")})

    print(f"XONG lô: {len(todo)} bản ghi | OK={stats['ok']} thiếu số/ngày={stats['thieu']} "
          f"lỗi={stats['loi']} dùng OCR={stats['ocr']}")


if __name__ == "__main__":
    main()
