#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Đợt 2: lấy danh sách + tải PDF bản án TAND cấp huyện (cũ) và TAND khu vực, theo từng Tòa.

Phương án A (3 VPS): --shard K/3 chỉ tải nhóm Tòa của máy K (vps/lower_courts.shard, tất định);
--test chỉ tải một Tòa nhỏ trong nhóm của máy để chạy thử. Mỗi Tòa có trên 1.500 bản án được
chia theo năm ban hành; không lọc loại vụ việc (loại vụ việc lấy từ bản ghi). Dữ liệu:
  <work>/data2/<city>/<mã Tòa>/<nhóm>/{records.jsonl, records_full.jsonl, pdfs/}
Xong mỗi nhóm ghi dấu <work>/state/done2/<mã Tòa>__<nhóm>; xong hết ghi <work>/DOWNLOAD2_DONE.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lower_courts  # noqa: E402

THIS_YEAR = datetime.now().year
SPLIT = 1500


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default="tp-hcm,ha-noi,da-nang", help="tp-hcm,ha-noi,da-nang")
    ap.add_argument("--shard", default=None, help="K/N: chỉ tải nhóm Tòa thứ K trong N máy")
    ap.add_argument("--test", action="store_true", help="chỉ tải một Tòa nhỏ trong nhóm (chạy thử)")
    ap.add_argument("--work", default=os.environ.get("TOAAN_WORK", "/root/work"))
    ap.add_argument("--courts-json", default=None)
    ap.add_argument("--python", default=str(REPO / ".venv" / "bin" / "python"))
    ap.add_argument("--min-free-gb", type=float, default=6)
    ap.add_argument("--headless", action="store_true", default=True)
    a = ap.parse_args()
    work = Path(a.work).expanduser().resolve()
    data, mark, logf = work / "data2", work / "state" / "done2", work / "logs" / "download2.log"
    logf.parent.mkdir(parents=True, exist_ok=True)

    def log(msg):
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
        print(line, flush=True)
        with logf.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def run(cmd, tries, wait):
        for i in range(1, tries + 1):
            with logf.open("a", encoding="utf-8") as f:
                rc = subprocess.run(cmd, cwd=REPO, stdout=f, stderr=subprocess.STDOUT).returncode
            if rc == 0:
                return True
            log(f"   lần {i}/{tries} lỗi (mã {rc}); nghỉ {wait}s")
            time.sleep(wait)
        return False

    def ids(p):
        s = set()
        if p.exists():
            for line in p.open(encoding="utf-8"):
                try:
                    s.add(json.loads(line).get("id"))
                except json.JSONDecodeError:
                    pass
        s.discard(None)
        return s

    QUARTERS = ((1, "01/01", "31/03"), (2, "01/04", "30/06"), (3, "01/07", "30/09"), (4, "01/10", "31/12"))

    def buckets(c):
        """Tòa > 1.500 bản: chia theo quý (danh sách trên cổng chậm dần ở các trang sâu; nhóm nhỏ ~25 trang
        nhanh hơn nhiều và tải PDF xen kẽ sớm hơn). Năm nào đã bắt đầu tải theo cả năm thì giữ nguyên."""
        if c["total"] <= SPLIT:
            return [("tat-ca", None, None)]
        kv = c["kind"] == "khu-vuc"
        b = [] if kv else [("truoc-2017", "01/01/1990", "31/12/2016")]
        if kv and not ((mark / f"{c['value']}__2025").exists()
                       or (data / c["city"] / c["value"] / "2025" / "records.jsonl").exists()):
            # Cổng gắn cho TAND khu vực cả bản án/quyết định ghi ngày trước 01/7/2025 (đo 06/11: thiếu ~10.000
            # bản ở các Tòa khu vực > 1.500 bản) → thêm một nhóm cho toàn bộ giai đoạn trước 01/7/2025
            b.append(("truoc-2025Q3", "01/01/1990", "30/06/2025"))
        # TAND cấp huyện chấm dứt hoạt động từ 01/7/2025 (TAND khu vực thay thế): không tìm sau 30/6/2025.
        # Truy vấn rỗng trên cổng không trả "0 kết quả" mà chờ đến hết thời gian (~15 phút/nhóm) → bỏ hẳn.
        for y in range(2025 if kv else 2017, (THIS_YEAR if kv else 2025) + 1):
            ydir = data / c["city"] / c["value"] / str(y)
            if (mark / f"{c['value']}__{y}").exists() or (ydir / "records.jsonl").exists():
                b.append((str(y), f"01/01/{y}", f"31/12/{y}"))
                continue
            for q, d1, d2 in QUARTERS:
                if kv and y == 2025 and q < 3:  # TAND khu vực hoạt động từ 01/7/2025
                    continue
                if not kv and y == 2025 and q > 2:  # TAND cấp huyện đến 30/6/2025
                    continue
                b.append((f"{y}-Q{q}", f"{d1}/{y}", f"{d2}/{y}"))
        return b

    def do(c, bucket, dfrom, dto, refresh=False):
        out = data / c["city"] / c["value"] / bucket
        out.mkdir(parents=True, exist_ok=True)
        mk = mark / f"{c['value']}__{bucket}"
        if mk.exists() and not refresh:
            return True
        if refresh:
            (out / "checkpoint.json").unlink(missing_ok=True)
        cmd = [a.python, "scrape_toaan.py", "--case-type", "tat-ca", "--level", "huyen", "--court-value", c["value"],
               "--out-dir", str(out), "--resume", "--delay", "1.5"]
        if dfrom:
            cmd += ["--date-from", dfrom, "--date-to", dto]
        tag = f"[{c['ma_noi']} {bucket}]"
        log(f"{tag} lấy danh sách{' (cập nhật)' if refresh else ''}")
        if not run(cmd, 4, 60):
            log(f"{tag} LỖI lấy danh sách — để lại")
            return False
        prev, fails = None, 0
        while True:
            while shutil.disk_usage(str(work)).free < a.min_free_gb * 1e9:
                log(f"Ổ còn dưới {a.min_free_gb:.0f} GB — tạm dừng tải 10 phút")
                time.sleep(600)
            if not run([a.python, "fetch_pdfs.py", "--records-dir", str(out), "--delay", "0.8",
                        "--max-records", "300"], 1, 60):
                fails += 1
                if fails >= 3:
                    log(f"{tag} LỖI tải PDF — để lại")
                    return False
                continue
            rem = len(ids(out / "records.jsonl") - ids(out / "records_full.jsonl"))
            if rem == 0 or rem == prev:
                if rem:
                    log(f"{tag} còn {rem} bản ghi không tải được PDF (bỏ qua)")
                break
            prev = rem
        # Ghi kèm thông tin Tòa vào thư mục để khâu tạo MD dùng
        (out / "court.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        mark.mkdir(parents=True, exist_ok=True)
        mk.write_text(datetime.now().isoformat(timespec="seconds"))
        log(f"{tag} XONG ({len(ids(out / 'records_full.jsonl'))} bản ghi)")
        return True

    cities = [x.strip() for x in a.cities.split(",") if x.strip()]
    cj = a.courts_json or str(work / "count_lower.json")
    courts = lower_courts.load(cj, cities)
    if a.shard:
        k, n = lower_courts.parse_shard(a.shard)
        courts = lower_courts.shard(courts, n)[k - 1]
        log(f"Nhóm máy {k}/{n}: {len(courts)} Tòa")
    if a.test:
        pick = [c for c in courts if "Cần Giờ" in c["name"]] or \
            sorted([c for c in courts if c["total"] >= 300] or courts, key=lambda c: c["total"])[:1]
        courts = pick[:1]
        log(f"CHẠY THỬ: chỉ tải {courts[0]['ma_noi']} ({courts[0]['total']} bản án)")
    log(f"===== Đợt 2: {len(courts)} Tòa ({', '.join(cities)}), "
        f"{lower_courts.fmt(sum(c['total'] for c in courts))} bản án theo số đếm =====")
    failed = []
    for _ in range(3):
        failed = []
        for c in courts:
            for b, f_, t_ in buckets(c):
                # court.json cần có ngay cả khi nhóm đang tải dở (khâu tạo MD đọc song song)
                d = data / c["city"] / c["value"] / b
                d.mkdir(parents=True, exist_ok=True)
                (d / "court.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
                if not do(c, b, f_, t_):
                    failed.append((c["ma_noi"], b))
        if not failed:
            break
        log(f"Còn {len(failed)} nhóm lỗi, nghỉ 15 phút rồi thử lại: {failed[:10]}")
        time.sleep(900)
    log("===== Lượt cập nhật: quý hiện tại + quý trước và các Tòa không chia năm =====")
    _q = (datetime.now().month - 1) // 3 + 1
    _y = THIS_YEAR
    recent_q = {f"{_y}-Q{_q}", (f"{_y}-Q{_q - 1}" if _q > 1 else f"{_y - 1}-Q4")}
    for c in ([] if a.test else courts):
        for b, f_, t_ in buckets(c):
            if c["kind"] != "khu-vuc" and b != "tat-ca":  # cấp huyện: không còn bản án mới
                continue
            if b in ("tat-ca", str(THIS_YEAR)) or b in recent_q:
                do(c, b, f_, t_, refresh=True)
    (work / ("DOWNLOAD2_TEST_DONE" if a.test else "DOWNLOAD2_DONE")).write_text(datetime.now().isoformat(timespec="seconds"))
    log(f"===== HOÀN TẤT đợt 2 ({', '.join(cities)}). Nhóm còn lỗi: {failed or 'không'} =====")


if __name__ == "__main__":
    main()
