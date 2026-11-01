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
import re
import shutil
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
BROKEN_FLAG = WORK / "state" / "date_filter_ineffective"
DATE_RE = re.compile(r"ng[àa]y\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", re.I)


def self_update():
    """Kéo bản mã mới nhất từ GitHub; nếu có thay đổi thì tự khởi động lại tiến trình."""
    try:
        old = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "pull", "-q", "--ff-only"], cwd=REPO, capture_output=True, timeout=60)
        new = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
        if old and new and old != new:
            log(f"Cập nhật mã nguồn {old[:7]} → {new[:7]}, khởi động lại")
            os.execv(sys.executable, [sys.executable, "-u", str(Path(__file__).resolve())])
    except Exception as e:  # noqa: BLE001
        log(f"Không cập nhật được mã nguồn: {e}")


def out_of_range_ratio(out_dir, dfrom, dto):
    """Tỷ lệ bản ghi có ngày ban hành nằm ngoài khoảng lọc (để phát hiện bộ lọc năm không có tác dụng)."""
    lo = datetime.strptime(dfrom, "%d/%m/%Y")
    hi = datetime.strptime(dto, "%d/%m/%Y")
    n = bad = 0
    p = out_dir / "records.jsonl"
    if not p.exists():
        return 0, 0.0
    for line in p.open(encoding="utf-8"):
        try:
            m = DATE_RE.search(json.loads(line).get("so_ngay_toa") or "")
        except json.JSONDecodeError:
            continue
        if not m:
            continue
        try:
            d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
        n += 1
        bad += not (lo <= d <= hi)
    return n, (bad / n if n else 0.0)


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _ids(path):
    ids = set()
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                rid = json.loads(line).get("id")
            except json.JSONDecodeError:
                continue
            if rid:
                ids.add(rid)
    return ids


def remaining_ids(out):
    """Số bản ghi đã có trong danh sách nhưng chưa qua bước tải PDF."""
    return len(_ids(out / "records.jsonl") - _ids(out / "records_full.jsonl"))


def existing_bucket(court, case_type):
    """Nhóm đã xong đầu tiên của (Tòa, loại vụ việc): (bucket, dfrom, dto) hoặc None."""
    for m in sorted(MARK.glob(f"{court}__{case_type}__*")):
        bucket = m.name.split("__", 2)[2]
        try:
            info = json.loads(m.read_text())
            return bucket, info.get("dfrom"), info.get("dto")
        except (json.JSONDecodeError, OSError):
            return bucket, None, None
    return None


def buckets_for(expected):
    if expected <= SPLIT_THRESHOLD or BROKEN_FLAG.exists():
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


def do_bucket(court, case_type, bucket, dfrom, dto, refresh=False, expected_total=0):
    out = DATA / court / case_type / bucket
    out.mkdir(parents=True, exist_ok=True)
    marker = MARK / f"{court}__{case_type}__{bucket}"
    if marker.exists() and not refresh:
        return True
    if BROKEN_FLAG.exists() and not refresh and existing_bucket(court, case_type):
        # Bộ lọc năm không có tác dụng: một nhóm đã lấy toàn bộ danh sách của (Tòa, loại vụ việc)
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
    if dfrom and expected_total:
        n, ratio = out_of_range_ratio(out, dfrom, dto)
        # Chỉ kết luận "bộ lọc năm không có tác dụng" khi nhóm năm này chứa gần như TOÀN BỘ danh sách
        # (>= 80% số đếm của cả Tòa/loại vụ việc). Một số ít bản ghi lệch năm là do dữ liệu của cổng.
        if n >= 0.8 * expected_total and ratio > 0.3:
            log(f"[{court}/{case_type}/{bucket}] {ratio:.0%} bản ghi nằm ngoài khoảng ngày lọc — cổng không áp dụng "
                "bộ lọc năm khi đã chọn Tòa. Nhóm này đã chứa toàn bộ danh sách; bỏ chia năm từ nay.")
            BROKEN_FLAG.parent.mkdir(parents=True, exist_ok=True)
            BROKEN_FLAG.write_text(f"{court}/{case_type}/{bucket}: {ratio:.0%} ngoài khoảng ({n} bản ghi)")
    log(f"[{court}/{case_type}/{bucket}] tải PDF")
    fails = 0
    prev = None
    while True:
        # Tải theo từng lô 300 file; giữ ổ đĩa luôn trống ít nhất 6 GB (khâu xử lý đẩy file lên Drive sẽ giải phóng chỗ)
        while shutil.disk_usage("/").free < 6e9:
            log("Ổ đĩa còn dưới 6 GB — tạm dừng tải PDF 10 phút, chờ khâu xử lý đẩy file lên Drive")
            time.sleep(600)
            self_update()
        if not run([PY, "fetch_pdfs.py", "--records-dir", str(out), "--delay", "0.8", "--max-records", "300"],
                   tries=1, wait=60):
            fails += 1
            if fails >= 3:
                log(f"[{court}/{case_type}/{bucket}] LỖI tải PDF — để lại, chạy lại sau")
                return False
            continue
        rem = remaining_ids(out)
        if rem == 0 or rem == prev:  # xong, hoặc còn vài bản ghi lỗi tải không giảm được nữa
            if rem:
                log(f"[{court}/{case_type}/{bucket}] còn {rem} bản ghi không tải được PDF (bỏ qua)")
            break
        prev = rem
    MARK.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"bucket": bucket, "dfrom": dfrom, "dto": dto,
                                  "at": datetime.now().isoformat(timespec="seconds")}))
    log(f"[{court}/{case_type}/{bucket}] XONG")
    return True


def main():
    self_update()
    expected = json.loads((REPO / "vps" / "expected_counts.json").read_text(encoding="utf-8"))
    log("===== Bắt đầu/tiếp tục lượt 1 =====")
    failed = []
    for _round in range(3):  # lượt 1, rồi thử lại tối đa 2 lần các nhóm còn lỗi
        failed = []
        for court in COURTS:
            for ct in CASE_TYPES:
                for bucket, dfrom, dto in buckets_for(expected[court][ct]):
                    self_update()
                    if not do_bucket(court, ct, bucket, dfrom, dto, expected_total=expected[court][ct]):
                        failed.append((court, ct, bucket))
        if not failed:
            break
        log(f"Còn {len(failed)} nhóm lỗi, nghỉ 15 phút rồi thử lại: {failed}")
        time.sleep(900)

    log("===== Lượt 2: cập nhật năm hiện tại và các nhóm không chia năm =====")
    for court in COURTS:
        for ct in CASE_TYPES:
            if BROKEN_FLAG.exists() and existing_bucket(court, ct):
                # Quét lại đúng nhóm đang giữ toàn bộ danh sách (khử trùng theo id, không tải lại PDF cũ)
                do_bucket(court, ct, *existing_bucket(court, ct), refresh=True)
                continue
            for bucket, dfrom, dto in buckets_for(expected[court][ct]):
                if bucket in ("tat-ca", str(THIS_YEAR)):
                    do_bucket(court, ct, bucket, dfrom, dto, refresh=True)

    (WORK / "DOWNLOAD_DONE").write_text(datetime.now().isoformat(timespec="seconds"))
    log(f"===== HOÀN TẤT tải. Nhóm còn lỗi sau lượt 1: {failed or 'không'} =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
