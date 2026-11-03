#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Đợt 2, phương án A: VPS tự đặt tên, tạo MD và chuẩn bị PDF để đẩy thẳng lên Google Drive "BANAN PDF".

Đọc <work>/data2/<city>/<mã Tòa>/<nhóm>/records_full.jsonl (vps/download_lower.py). Với mỗi bản ghi đã có PDF:
  1. Đọc lớp chữ bằng pdftotext (KHÔNG OCR trên VPS). Phân loại:
       NATIVE           mọi trang có chữ
       NATIVE_MOT_PHAN  có trang là ảnh scan (ghi số trang vào trang_anh)
       CAN_OCR          không có lớp chữ (bản scan) — OCR sau trên MacBook
  2. Đặt tên  YYYYMMDD - <mã Nơi> - <Giai đoạn>-<Loại>-<Năm>-<Số> - <Quan hệ pháp luật>
     (vd "20230512 - HCM-Quận 1 - ST-DS-2023-145 - Tranh chấp ..."); thiếu số/ngày → "_CHUA DAT TEN".
  3. Ghi MD (YAML + toàn văn) vào <work>/md2/<rel>/ — MacBook kéo về MDBANAN (tools/dot2_mac.sh keo).
     Chuyển PDF sang <work>/upload2/<rel>/ — vps/upload3.sh đẩy lên BANAN PDF/<rel>/ rồi xóa khỏi VPS.
     <rel> = <THÀNH PHỐ>/CAP HUYEN - KHU VUC/<NN LOẠI VỤ VIỆC>[/_CHUA DAT TEN]
  4. Ghi <work>/state/processed2.csv để chạy lại không xử lý trùng.
  --loop  chạy mãi (dịch vụ toaan-process2); --once  một lượt.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "mac"))
import process as P  # noqa: E402  (đặt tên: build_stem, CASE_TYPE_DIR)
import lower_courts  # noqa: E402
import frontmatter as FM  # noqa: E402  (YAML, tách tên Thẩm phán/Thư ký/KSV)

WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
DATA2, MD2, UP = WORK / "data2", WORK / "md2", WORK / "upload2"
STATE_CSV = WORK / "state" / "processed2.csv"
LOG = WORK / "logs" / "process2.log"
FIELDNAMES = P.FIELDNAMES + ["so_trang", "trang_anh"]
LEVEL_DIR = "CAP HUYEN - KHU VUC"
PDF_LABEL = "BANAN PDF"
CASE_LABEL = {
    "dan-su": "Dân sự", "hinh-su": "Hình sự", "kinh-doanh-thuong-mai": "Kinh doanh thương mại",
    "hon-nhan-gia-dinh": "Hôn nhân và gia đình", "lao-dong": "Lao động", "pha-san": "Phá sản",
    "hanh-chinh": "Hành chính", "xu-ly-hanh-chinh": "Xử lý hành chính",
}
MIN_PAGE_CHARS = 40   # trang có ít hơn số ký tự (không tính khoảng trắng) này coi là ảnh scan
MIN_DOC_CHARS = 60
MAX_STEM_BYTES = 200  # macOS giới hạn tên file 255 byte; chữ Việt 2–3 byte/ký tự, chừa chỗ cho " (bản n).md"


def fit_bytes(stem):
    """Cắt phần trích yếu (sau dấu ' - ' thứ ba) để tên file không quá MAX_STEM_BYTES byte UTF-8."""
    stem = unicodedata.normalize("NFC", stem)
    if len(stem.encode("utf-8")) <= MAX_STEM_BYTES:
        return stem
    while len(stem.encode("utf-8")) > MAX_STEM_BYTES - 1:
        stem = stem[:-1]
    return stem.rstrip(" -,.;") + "…"


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def pdf_ok(path):
    """PDF đủ: bắt đầu bằng %PDF và có %%EOF ở cuối (bắt file tải thiếu/không phải PDF)."""
    try:
        with open(path, "rb") as f:
            head = f.read(5)
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 2048))
            tail = f.read()
        return head.startswith(b"%PDF") and b"%%EOF" in tail
    except OSError:
        return False


def extract(pdf_path):
    """Trả về (văn bản, phương pháp, số trang, [trang ảnh]). Chỉ đọc lớp chữ, không OCR."""
    npages = 0
    try:
        info = subprocess.run(["pdfinfo", pdf_path], capture_output=True, text=True, timeout=60).stdout or ""
        m = re.search(r"^Pages:\s*(\d+)", info, re.M)
        npages = int(m.group(1)) if m else 0
    except Exception:  # noqa: BLE001
        pass
    try:
        raw = subprocess.run(["pdftotext", "-layout", pdf_path, "-"], capture_output=True, text=True,
                             timeout=180).stdout or ""
    except Exception:  # noqa: BLE001
        raw = ""
    pages = raw.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    if npages and len(pages) > npages:
        pages = pages[:npages]
    npages = npages or len(pages)
    if len(re.sub(r"\s", "", raw)) < MIN_DOC_CHARS:
        return "", "CAN_OCR", npages, list(range(1, npages + 1))
    anh = [i for i, p in enumerate(pages, 1) if len(re.sub(r"\s", "", p)) < MIN_PAGE_CHARS]
    if not anh:
        return "\n\n".join(pages), "NATIVE", npages, []
    parts = [f"[… trang {i}: ảnh scan, chưa OCR — xem PDF gốc …]" if i in anh else p
             for i, p in enumerate(pages, 1)]
    return "\n\n".join(parts), "NATIVE_MOT_PHAN", npages, anh


_CT_FROM_SO = (("XLHC", "xu-ly-hanh-chinh"), ("KDTM", "kinh-doanh-thuong-mai"), ("HNG", "hon-nhan-gia-dinh"),
               ("HS", "hinh-su"), ("LD", "lao-dong"), ("HC", "hanh-chinh"), ("PS", "pha-san"), ("DS", "dan-su"))


def _so_raw(rec):
    m = P.SO_NGAY_RE.search(rec.get("so_ngay_toa") or "")
    return m.group(1).strip().lstrip(":").strip() if m else ""


def so_ngan(so_raw):
    """Số bản án/quyết định trong tên file: '93/2017/HSST' → '93'; '214' → '214'."""
    m = re.match(r"(\d+)\s*/", so_raw)
    return m.group(1) if m else re.sub(r"[^0-9A-Za-z]", "", so_raw)


def loai_tu_so(so_raw):
    """Loại vụ việc suy từ ký hiệu trong số (vd '38/2017/HNGĐ-ST' → hôn nhân gia đình)."""
    t = lower_courts._kd(so_raw).upper()
    t = t.split("/", 1)[1] if "/" in t else ""
    letters = re.sub(r"[^A-Z]", "", t).replace("QD", "")
    for pat, key in _CT_FROM_SO:
        if pat in letters:
            return key
    return None


def loai_tu_qhpl(rec):
    t = lower_courts._kd(rec.get("quan_he_phap_luat") or "")
    if "pham toi" in t or re.search(r"\btoi\b", t):
        return "hinh-su"
    if "ly hon" in t or "hon nhan" in t:
        return "hon-nhan-gia-dinh"
    return None


def case_type2(rec):
    ct = lower_courts.case_type_of(rec)
    if ct == "khac":
        ct = loai_tu_so(_so_raw(rec)) or loai_tu_qhpl(rec) or "khac"
    return ct


def build_stem2(rec, ma_noi, case_type):
    m = P.SO_NGAY_RE.search(rec.get("so_ngay_toa") or "")
    if not m:
        return None
    d, mo, y = int(m.group(2)), int(m.group(3)), int(m.group(4))
    if not (1 <= d <= 31 and 1 <= mo <= 12 and 1900 <= y <= 2100):
        return None
    so = so_ngan(_so_raw(rec))
    if not so:
        return None
    ma = f"{P.phase_code_of(rec.get('cap_xet_xu'))}-{P.CASE_TYPE_CODE.get(case_type, 'KHAC')}-{y}-{so}"
    tom_tat = P.sanitize(rec.get("quan_he_phap_luat") or rec.get("thong_tin_vu_viec") or "")
    return f"{y:04d}{mo:02d}{d:02d} - {ma_noi} - {ma} - {tom_tat}"


def target(court, rec):
    """(rel, stem, case_type, thiếu số/ngày) — dùng chung cho process2 và fix_names2."""
    rec = {k: _sp(v) for k, v in rec.items()}
    ct = case_type2(rec)
    rel = Path(P.COURT_DIR[court["city"]]) / LEVEL_DIR / P.CASE_TYPE_DIR.get(ct, "09 KHAC")
    stem = build_stem2(rec, court["ma_noi"], ct)
    thieu = stem is None
    if thieu:
        stem = f"{rec['id']} - CHUA_XAC_DINH"
        rel = rel / "_CHUA DAT TEN"
    return rel, fit_bytes(stem), ct, thieu


def load_state():
    done, used = set(), set()
    if STATE_CSV.exists():
        with STATE_CSV.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                done.add(r["id"])
                used.add((r["dest_dir"], r["final_stem"]))
    return done, used


def candidates(done, limit):
    out = []
    for rf in sorted(DATA2.glob("*/*/*/records_full.jsonl")):
        cj = rf.parent / "court.json"
        if not cj.exists():
            continue
        court = json.loads(cj.read_text(encoding="utf-8"))
        with rf.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:  # dòng cuối fetch_pdfs.py đang ghi dở
                    continue
                rid = rec.get("id")
                if not rid or rid in done or not rec.get("pdf_path") or not os.path.exists(rec["pdf_path"]):
                    continue
                done.add(rid)
                out.append((court, rec))
                if len(out) >= limit:
                    return out
    return out


def _sp(v):
    """Gộp khoảng trắng thừa trong trường lấy từ cổng (vd "Hồ Chí Minh,  TP. Hồ Chí Minh")."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", v)).strip() if isinstance(v, str) else v


def write_one(court, rec, res, used):
    text, method, npages, anh = res
    rec = {k: _sp(v) for k, v in rec.items()}
    rid = rec["id"]
    rel, stem, case_type, thieu = target(court, rec)
    final, n = stem, 2
    while (str(rel), final) in used:
        final = f"{stem} (bản {n})"
        n += 1
    used.add((str(rel), final))
    hong = not pdf_ok(rec["pdf_path"])

    nguoi = FM.tach_nguoi_tien_hanh_to_tung(text) if text else {"tham_phan": [], "thu_ky": [], "kiem_sat_vien": []}
    fields = {
        "toa": rec.get("toa_an_xet_xu") or court["name"],
        "cap": court["kind"],
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
        "kiem_tra_ten": method != "NATIVE",
        "can_ocr": method != "NATIVE",
        "trang_anh": anh if method == "NATIVE_MOT_PHAN" else [],
        "so_trang": npages,
        "pdf_hong": hong,
        "ap_dung_an_le": rec.get("ap_dung_an_le", ""),
        "dinh_chinh": rec.get("dinh_chinh", ""),
        "ma_cong": rid,
        "nguon": rec.get("url_chi_tiet", ""),
        "pdf_goc": rec.get("pdf_url", ""),
        "pdf": str(Path(PDF_LABEL) / rel / f"{final}.pdf"),
        "trich_xuat": method,
        "ngay_tai": datetime.now().strftime("%Y-%m-%d"),
    }
    if method == "CAN_OCR":
        body = "(Bản scan chưa có lớp chữ — sẽ OCR sau trên MacBook. Xem PDF gốc.)"
    else:
        body = text
    status = "THIEU" if thieu else "OK"
    note = "pdf_hong" if hong else ""
    try:
        md_dir, up_dir = MD2 / rel, UP / rel
        md_dir.mkdir(parents=True, exist_ok=True)
        up_dir.mkdir(parents=True, exist_ok=True)
        tmp = md_dir / f".{final}.md.tmp"
        tmp.write_text(FM.build(fields) + f"\n# {final}\n\n" + body, encoding="utf-8")
        os.replace(tmp, md_dir / f"{final}.md")
        os.replace(rec["pdf_path"], up_dir / f"{final}.pdf")  # cùng ổ đĩa: đổi chỗ tức thời
    except Exception as e:  # noqa: BLE001
        status, note = "LOI", str(e)
    return {"id": rid, "court": court["value"], "case_type": case_type, "status": status, "final_stem": final,
            "dest_dir": str(rel), "method": method, "note": note,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "so_trang": npages, "trang_anh": " ".join(map(str, anh)) if method == "NATIVE_MOT_PHAN" else ""}


def one_pass(batch, workers):
    done, used = load_state()
    todo = candidates(done, batch)
    if not todo:
        return {}
    stats = {}
    STATE_CSV.parent.mkdir(parents=True, exist_ok=True)
    header = not STATE_CSV.exists()
    with ProcessPoolExecutor(max_workers=workers) as ex, STATE_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if header:
            w.writeheader()
        # map giữ thứ tự → tên "(bản n)" ổn định giữa các lần chạy
        for (court, rec), res in zip(todo, ex.map(extract, [r["pdf_path"] for _, r in todo], chunksize=4)):
            row = write_one(court, rec, res, used)
            w.writerow(row)
            f.flush()
            key = row["status"] if row["status"] != "OK" else row["method"]
            stats[key] = stats.get(key, 0) + 1
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--every", type=int, default=60)
    a = ap.parse_args()
    while True:
        try:
            st = one_pass(a.batch, a.workers)
            if st:
                log("xử lý lô: " + ", ".join(f"{k}={v}" for k, v in sorted(st.items())))
                continue  # còn việc: làm tiếp ngay
        except Exception as e:  # noqa: BLE001
            log(f"LỖI: {e}")
        if not a.loop:
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
