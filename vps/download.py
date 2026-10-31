#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vps/download.py — Điều phối việc lấy danh sách + tải PDF bản án TAND cấp tỉnh
TP. Hồ Chí Minh → Hà Nội → Đà Nẵng, cả 8 loại vụ việc, từ trước đến nay.

- Loại vụ việc có trên 1.500 bản ghi được chia theo năm ban hành (trước 2017, 2017, 2018, ...),
  để mỗi lần tìm kiếm có ít trang, thứ tự ổn định, không bị trượt trang khi cổng công bố thêm án mới.
- Mỗi nhóm chạy scrape_toaan.py (có --resume) rồi fetch_pdfs.py; thành công thì ghi dấu
  "đã xong" để lần khởi động lại (mất điện, khởi động lại máy) bỏ qua.
- Hết lượt 1, chạy lượt 2 cho năm hiện tại và các nhóm không chia năm, để lấy thêm án mới công bố.
- Xong toàn bộ thì tạo file DOWNLOAD_DONE.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = Path(os.environ.get("TOAAN_WORK", "/root/work"))
DATA = WORK / "data"
MARK = WORK / "state" / "done"
LOG = WORK / "logs" / "download.log"
PY = str(REPO / ".venv" / "bin" / "python")

COURTS = {  # mã Tòa trong dropdown của cổng, và biểu thức kiểm tra tên Tòa trong "số/ngày/tòa"
    "tp-hcm": ("787", r"H[ồô]\s*Ch[íi]\s*Minh"),
    "ha-noi": ("784", r"H[àa]\s*N[ộo]i"),
    "da-nang": ("775", r"[ĐD][àa]\s*N[ẵa]ng"),
}
CASE_TYPES = ["dan-su", "hinh-su", "hon-nhan-gia-dinh", "kinh-doanh-thuong-mai",
              "hanh-chinh", "lao-dong", "pha-san", "xu-ly-hanh-chinh"]
SPLIT_THRESHOLD = 1500
THIS_YEAR = datetime.now().year


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def buckets_for(expected):
    if expected <= SPLIT_THRESHOLD:
        return [("tat-ca", None, None)]
    b = [("truoc-2017", "01/01/1990", "31/12/2016")]
    b += [(str(y), f"01/01/{y}", f"31/12/{y}") for y in range(2017, THIS_YEAR + 1)]
    return b


def run(cmd, tries, wait):
    for i in range(1, tries + 1):
        with LOG.open("a", encoding="utf-8") as f:
            rc = subprocess.run(cmd, cwd=REPO, stdout=f, stderr=subprocess.STDOUT).returncode
        if rc == 0:
            return True
        log(f"   lần {i}/{tries} lỗi (mã {rc}); nghỉ {wait}s rồi thử lại")
        time.sleep(wait)
    return False


def do_bucket(court, case_type, bucket, dfrom, dto, refresh=False):
    out = DATA / court / case_type / bucket
    out.mkdir(parents=True, exist_ok=True)
    marker = MARK / f"{court}__{case_type}__{bucket}"
    if marker.exists() and not refresh:
        return True
    if refresh:
        (out / "checkpoint.json").unlink(missing_ok=True)
    value, regex = COURTS[court]
    scrape = [PY, "scrape_toaan.py", "--case-type", case_type, "--level", "tinh",
              "--court-value", value, "--court-regex", regex, "--out-dir", str(out),
              "--resume", "--delay", "1.5"]
    if dfrom:
        scrape += ["--date-from", dfrom, "--date-to", dto]
    log(f"[{court}/{case_type}/{bucket}] lấy danh sách{' (lượt cập nhật)' if refresh else ''}")
    if not run(scrape, tries=4, wait=60):
        log(f"[{court}/{case_type}/{bucket}] LỖI lấy danh sách — để lại, chạy lại sau")
        return False
    log(f"[{court}/{case_type}/{bucket}] tải PDF")
    if not run([PY, "fetch_pdfs.py", "--records-dir", str(out), "--delay", "0.8"], tries=3, wait=60):
        log(f"[{court}/{case_type}/{bucket}] LỖI tải PDF — để lại, chạy lại sau")
        return False
    MARK.mkdir(parents=True, exist_ok=True)
    marker.write_text(datetime.now().isoformat(timespec="seconds"))
    log(f"[{court}/{case_type}/{bucket}] XONG")
    return True


def main():
    expected = json.loads((REPO / "vps" / "expected_counts.json").read_text(encoding="utf-8"))
    log("===== Bắt đầu/tiếp tục lượt 1 =====")
    failed = []
    for _round in range(3):  # lượt 1, rồi thử lại tối đa 2 lần các nhóm còn lỗi
        failed = []
        for court in COURTS:
            for ct in CASE_TYPES:
                for bucket, dfrom, dto in buckets_for(expected[court][ct]):
                    if not do_bucket(court, ct, bucket, dfrom, dto):
                        failed.append((court, ct, bucket))
        if not failed:
            break
        log(f"Còn {len(failed)} nhóm lỗi, nghỉ 15 phút rồi thử lại: {failed}")
        time.sleep(900)

    log("===== Lượt 2: cập nhật năm hiện tại và các nhóm không chia năm =====")
    for court in COURTS:
        for ct in CASE_TYPES:
            for bucket, dfrom, dto in buckets_for(expected[court][ct]):
                if bucket in ("tat-ca", str(THIS_YEAR)):
                    do_bucket(court, ct, bucket, dfrom, dto, refresh=True)

    (WORK / "DOWNLOAD_DONE").write_text(datetime.now().isoformat(timespec="seconds"))
    log(f"===== HOÀN TẤT tải. Nhóm còn lỗi sau lượt 1: {failed or 'không'} =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
