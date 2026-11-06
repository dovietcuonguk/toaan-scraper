#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Đợt 2: OCR các trang ảnh của bản NATIVE_MOT_PHAN (chỉ những trang ghi trong trang_anh).

Không tạo MD mới, không sửa PDF trên Drive:
  1. Đọc <work>/state/processed2.csv → bản có trang_anh, chưa OCR (state/ocr2_done.txt).
  2. Lấy PDF: còn trong upload2 thì chép tạm; đã lên Drive thì rclone COPY (không move) về ocr2_tmp.
  3. pdftoppm 300 dpi + tesseract tiếng Việt từng trang ảnh; xóa ảnh/PDF tạm ngay sau đó.
  4. Ghi <work>/outbox_ocr/ocr-<thời điểm>/<id>.json {id, md, pages{trang: chữ}, tham_phan, thu_ky,
     kiem_sat_vien}. MacBook kéo về rồi ghép vào MD đang có (tools/ocr_ghep.py, lệnh dot2_mac.sh ghepocr).
Cách chạy:
  --dem        đếm số bản / trang ảnh còn phải OCR trên máy này
  --thu N      OCR thật N bản, đo tốc độ, ước tính thời gian cho phần còn lại
  --loop       chạy mãi (10 phút/lượt); tự dừng khi DOT2_ALL_DONE có và không còn gì để OCR
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "mac"))
import frontmatter as FM  # noqa: E402

WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
STATE_CSV = WORK / "state" / "processed2.csv"
DONE = WORK / "state" / "ocr2_done.txt"
LOI = WORK / "state" / "ocr2_loi.txt"  # mỗi lần lỗi/không lấy được PDF ghi một dòng id; lỗi 3 lần thì bỏ qua
OB, TMP, UP = WORK / "outbox_ocr", WORK / "ocr2_tmp", WORK / "upload2"
LOG = WORK / "logs" / "ocr2.log"
CHUNK = 200


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_done():
    done = set(DONE.read_text(encoding="utf-8").split()) if DONE.exists() else set()
    if LOI.exists():
        from collections import Counter
        done |= {i for i, c in Counter(LOI.read_text(encoding="utf-8").split()).items() if c >= 3}
    return done


def ghi_loi(ids):
    if ids:
        with LOI.open("a", encoding="utf-8") as f:
            f.write("".join(i + "\n" for i in ids))


def todo_rows(done):
    last = {}
    if STATE_CSV.exists():
        with STATE_CSV.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                last[r["id"]] = r  # dòng sau cùng của mỗi id là tên hiện hành (fix_names2 ghi lại cả tệp)
    out = []
    for rid, r in last.items():
        if rid in done or r.get("status") not in ("OK", "THIEU"):
            continue
        pages = [int(x) for x in (r.get("trang_anh") or "").split() if x.isdigit()]
        if pages:
            out.append(dict(r, pages=pages))
    return out


def rel_pdf(r):
    return f"{r['dest_dir']}/{r['final_stem']}.pdf"


def ocr_page(pdf, p, tmpdir):
    base = Path(tmpdir) / f"p{p}"
    subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", "300", "-gray", "-png", "-singlefile",
                    str(pdf), str(base)], timeout=180, check=True, capture_output=True)
    png = base.with_suffix(".png")
    try:
        r = subprocess.run(["tesseract", str(png), "stdout", "-l", "vie", "--psm", "4"], capture_output=True,
                           text=True, timeout=600, env=dict(os.environ, OMP_THREAD_LIMIT="1"))
        return (r.stdout or "").strip()
    finally:
        png.unlink(missing_ok=True)


def work_one(job):
    r, pdf = job
    t0 = time.time()
    tmpdir = Path(str(pdf) + ".d")
    tmpdir.mkdir(exist_ok=True)
    try:
        pages = {}
        for p in r["pages"]:
            pages[str(p)] = ocr_page(pdf, p, tmpdir)
        raw = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True,
                             timeout=180).stdout or ""
        parts = raw.split("\f")
        full = "\n\n".join(pages.get(str(i), t) for i, t in enumerate(parts, 1))
        nguoi = FM.tach_nguoi_tien_hanh_to_tung(full)
        return {"id": r["id"], "md": f"{r['dest_dir']}/{r['final_stem']}.md", "pages": pages, **nguoi,
                "giay": round(time.time() - t0, 1)}, None
    except Exception as e:  # noqa: BLE001
        return None, (r["id"], str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def fetch(chunk, dl):
    """Trả về [(row, đường dẫn PDF tạm)] cho những bản lấy được."""
    dl.mkdir(parents=True, exist_ok=True)
    jobs, need = [], []
    for r in chunk:
        loc = UP / rel_pdf(r)
        dst = dl / rel_pdf(r)
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(loc, dst)  # chưa lên Drive: chép tạm (upload3 có thể chuyển đi bất cứ lúc nào)
            jobs.append((r, dst))
        except OSError:
            need.append(r)
    if need:
        lst = dl / ".danh_sach.txt"
        lst.write_text("".join(rel_pdf(r) + "\n" for r in need), encoding="utf-8")
        subprocess.run(["rclone", "copy", "banan:", str(dl), "--files-from-raw", str(lst), "--transfers", "8",
                        "--checkers", "8", "--tpslimit", "8", "--retries", "3", "--low-level-retries", "5",
                        "--log-file", str(WORK / "logs" / "rclone_ocr2.log"), "--log-level", "NOTICE"])
        for r in need:
            dst = dl / rel_pdf(r)
            if dst.exists():
                jobs.append((r, dst))
    return jobs


def one_pass(rows, workers):
    done_f = DONE.open("a", encoding="utf-8")
    n_ok = n_pages = n_err = 0
    t0 = time.time()
    for k in range(0, len(rows), CHUNK):
        chunk = rows[k:k + CHUNK]
        dl = TMP / f"c{k}"
        shutil.rmtree(dl, ignore_errors=True)
        jobs = fetch(chunk, dl)
        got = {r["id"] for r, _ in jobs}
        miss = [r["id"] for r in chunk if r["id"] not in got]
        ghi_loi(miss)
        stamp = datetime.now().strftime("%Y%m%d%H%M%S") + f"-{k // CHUNK}"
        tmp_out = OB / f".tmp-{stamp}"
        tmp_out.mkdir(parents=True, exist_ok=True)
        ok_ids = []
        with ProcessPoolExecutor(workers) as ex:
            for res, err in ex.map(work_one, jobs):
                if err:
                    n_err += 1
                    ghi_loi([err[0]])
                    log(f"  lỗi {err[0]}: {err[1][:200]}")
                    continue
                (tmp_out / f"{res['id']}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
                ok_ids.append(res["id"])
                n_pages += len(res["pages"])
        if ok_ids:
            os.replace(tmp_out, OB / f"ocr-{stamp}")  # MacBook chỉ thấy lô khi đã đủ
            done_f.write("".join(i + "\n" for i in ok_ids))
            done_f.flush()
        else:
            shutil.rmtree(tmp_out, ignore_errors=True)
        shutil.rmtree(dl, ignore_errors=True)
        n_ok += len(ok_ids)
        el = time.time() - t0
        log(f"  {n_ok}/{len(rows)} bản, {n_pages} trang · {n_pages / el * 3600:,.0f} trang/giờ"
            + (f" · {len(miss)} bản chưa lấy được PDF (thử lại lượt sau, tối đa 3 lần)" if miss else ""))
    done_f.close()
    return n_ok, n_pages, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dem", action="store_true")
    ap.add_argument("--thu", type=int, default=0)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    a = ap.parse_args()
    for t in ("tesseract", "pdftoppm", "pdftotext", "rclone"):
        if not shutil.which(t):
            sys.exit(f"Thiếu {t}: apt-get install -y tesseract-ocr tesseract-ocr-vie poppler-utils rclone")
    rows = todo_rows(load_done())
    pages = sum(len(r["pages"]) for r in rows)
    if a.dem:
        n_done = len(DONE.read_text(encoding="utf-8").split()) if DONE.exists() else 0
        print(f"CPU {os.cpu_count()} · còn {len(rows):,} bản / {pages:,} trang ảnh"
              f" · TB {pages / max(len(rows), 1):.1f} trang/bản · đã OCR {n_done:,} bản")
        return
    if a.thu:
        n, pg, el = one_pass(rows[:a.thu], a.workers)
        rate = pg / el * 3600 if el else 0
        rest = pages - pg
        print(f"THỬ: {n} bản, {pg} trang trong {el:.0f} giây = {rate:,.0f} trang/giờ ({a.workers} tiến trình)")
        print(f"Còn {rest:,} trang ảnh trên máy này → khoảng {rest / rate:.1f} giờ" if rate else "Không đo được")
        return
    while True:
        rows = todo_rows(load_done())
        if rows:
            log(f"===== Lượt OCR: {len(rows):,} bản / {sum(len(r['pages']) for r in rows):,} trang ảnh =====")
            one_pass(rows, a.workers)
        if not a.loop:
            return
        if not rows and (WORK / "DOT2_ALL_DONE").exists():
            (WORK / "OCR2_DONE").write_text(datetime.now().isoformat(timespec="seconds"))
            log("===== OCR xong toàn bộ bản NATIVE_MOT_PHAN của máy này =====")
            return
        time.sleep(600)


if __name__ == "__main__":
    main()
