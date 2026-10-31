#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_pdfs.py
=============
Bước 2 (tùy chọn) sau khi đã chạy scrape_toaan.py.

Đọc file records.jsonl (do scrape_toaan.py tạo ra), với MỖI bản ghi:
  - Tải trang chi tiết (GET thường, không cần trình duyệt) để lấy:
      + Tên tòa án xét xử đầy đủ ("Tòa án xét xử")
      + Đường link file PDF gốc do Tòa án công bố
  - Tải file PDF gốc về thư mục con "pdfs/"
  - Ghi kết quả bổ sung vào file "records_full.jsonl" (mỗi dòng = record gốc
    + các trường mới: toa_an_xet_xu, pdf_url, pdf_path)

Vì trang chi tiết là URL tĩnh (không qua postback), bước này dùng httpx
(HTTP thuần) thay vì Playwright nên nhanh hơn nhiều so với bước 1.

CÁCH DÙNG:
  python fetch_pdfs.py --records-dir data/dan-su --delay 0.8

Có thể dừng (Ctrl+C) và chạy lại — các bản ghi đã xử lý (đã có trong
records_full.jsonl hoặc đã có file PDF) sẽ được bỏ qua.
"""

import argparse
import json
import logging
import re
import signal
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, unquote

try:
    import httpx
except ImportError:
    sys.exit("Thiếu thư viện httpx. Cài đặt bằng: pip install -r requirements.txt")

# Lỗi "[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate"
# thường gặp trên macOS khi Python cài qua trình cài đặt python.org: bộ chứng
# chỉ CA đi kèm bản Python đó không đầy đủ (thiếu chứng chỉ gốc/trung gian mà
# Keychain của macOS — và do đó Chrome/Safari — đã có sẵn), dù trang vẫn hoàn
# toàn hợp lệ khi mở bằng trình duyệt thật. Dùng thư viện "truststore" để
# httpx/ssl xác thực chứng chỉ THẲNG qua kho tin cậy của hệ điều hành (macOS
# Keychain) thay vì bộ chứng chỉ đóng gói riêng của Python — đúng cơ chế mà
# trình duyệt dùng, nên sẽ hết lỗi này mà KHÔNG cần tắt xác thực SSL (verify=False,
# vốn kém an toàn hơn).
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    sys.exit(
        "Thiếu thư viện truststore (cần để sửa lỗi SSL CERTIFICATE_VERIFY_FAILED "
        "trên macOS). Cài đặt bằng: pip install -r requirements.txt"
    )

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Thiếu thư viện beautifulsoup4. Cài đặt bằng: pip install -r requirements.txt")


BASE_URL = "https://congbobanan.toaan.gov.vn"
LISTING_URL = f"{BASE_URL}/0tat1cvn/ban-an-quyet-dinh"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def build_logger(log_path: Path) -> logging.Logger:
    log = logging.getLogger("fetch_pdfs")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


def field_value(soup: BeautifulSoup, label_text: str):
    label = soup.find("label", string=re.compile(re.escape(label_text)))
    if not label:
        return None
    sib = label.find_next_sibling("span")
    return sib.get_text(" ", strip=True) if sib else None


def extract_detail(html: str):
    soup = BeautifulSoup(html, "html.parser")
    toa_an = field_value(soup, "Tòa án xét xử")
    pdf_href = None
    for a in soup.select('div.btn_set_color a[href]'):
        href = a.get("href", "")
        if href.lower().endswith(".pdf"):
            pdf_href = href
            break
    return toa_an, pdf_href


def safe_filename(name: str, fallback: str) -> str:
    name = unquote(name)
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip() or fallback
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def load_done_ids(records_full_path: Path) -> set:
    done = set()
    if not records_full_path.exists():
        return done
    with records_full_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rid = json.loads(line).get("id")
                if rid:
                    done.add(rid)
            except json.JSONDecodeError:
                continue
    return done


def run(args):
    records_dir = Path(args.records_dir)
    records_path = records_dir / "records.jsonl"
    if not records_path.exists():
        sys.exit(f"Không tìm thấy {records_path}. Hãy chạy scrape_toaan.py trước.")

    pdf_dir = records_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    records_full_path = records_dir / "records_full.jsonl"
    log = build_logger(records_dir / "fetch_pdfs.log")

    done_ids = load_done_ids(records_full_path)
    log.info(f"Đã có {len(done_ids)} bản ghi xử lý từ trước, sẽ bỏ qua.")

    stop_flag = {"stop": False}

    def handle_sigint(signum, frame):
        log.warning("Nhận Ctrl+C — sẽ dừng an toàn sau bản ghi hiện tại...")
        stop_flag["stop"] = True

    signal.signal(signal.SIGINT, handle_sigint)

    with records_path.open(encoding="utf-8") as f:
        all_records = [json.loads(line) for line in f if line.strip()]

    todo = [r for r in all_records if r.get("id") and r["id"] not in done_ids]
    if args.max_records:
        todo = todo[: args.max_records]
    log.info(f"Sẽ xử lý {len(todo)}/{len(all_records)} bản ghi.")

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "vi-VN,vi;q=0.9"}
    processed = 0
    with httpx.Client(headers=headers, follow_redirects=True, timeout=30.0) as client:
        # Gọi trang danh sách trước để nhận cookie phiên (nếu server yêu cầu)
        try:
            client.get(LISTING_URL)
        except httpx.HTTPError as e:
            log.warning(f"Không truy cập được trang danh sách để lấy cookie: {e}")

        with records_full_path.open("a", encoding="utf-8") as fout:
            for rec in todo:
                if stop_flag["stop"]:
                    break
                url = rec.get("url_chi_tiet")
                if not url:
                    continue
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                except httpx.HTTPError as e:
                    log.error(f"[{rec['id']}] Lỗi tải trang chi tiết: {e}")
                    time.sleep(args.delay)
                    continue

                toa_an, pdf_href = extract_detail(resp.text)
                rec["toa_an_xet_xu"] = toa_an
                rec["pdf_url"] = urljoin(BASE_URL, pdf_href) if pdf_href else None
                rec["pdf_path"] = None

                if pdf_href and args.download_pdf:
                    pdf_url = urljoin(BASE_URL, pdf_href)
                    fname = safe_filename(pdf_href.rsplit("/", 1)[-1], rec["id"])
                    dest = pdf_dir / f"{rec['id']}_{fname}"
                    if not dest.exists():
                        try:
                            with client.stream("GET", pdf_url) as r:
                                r.raise_for_status()
                                with dest.open("wb") as fpdf:
                                    for chunk in r.iter_bytes():
                                        fpdf.write(chunk)
                        except httpx.HTTPError as e:
                            log.error(f"[{rec['id']}] Lỗi tải PDF: {e}")
                            dest = None
                    if dest:
                        rec["pdf_path"] = str(dest)

                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fout.flush()
                processed += 1
                if processed % 20 == 0:
                    log.info(f"Đã xử lý {processed}/{len(todo)} bản ghi...")
                time.sleep(args.delay)

    log.info(f"Hoàn tất. Đã xử lý {processed} bản ghi mới. Xem: {records_full_path}")


def parse_args():
    ap = argparse.ArgumentParser(description="Tải trang chi tiết + PDF gốc cho các bản ghi đã thu thập")
    ap.add_argument("--records-dir", required=True, help="Thư mục chứa records.jsonl (do scrape_toaan.py tạo)")
    ap.add_argument("--max-records", type=int, default=None, help="Giới hạn số bản ghi xử lý trong lần chạy này")
    ap.add_argument("--delay", type=float, default=0.8, help="Số giây nghỉ giữa mỗi request (mặc định 0.8s)")
    ap.add_argument(
        "--download-pdf",
        action="store_true",
        default=True,
        help="Tải file PDF gốc về máy (mặc định: có)",
    )
    ap.add_argument(
        "--no-download-pdf",
        dest="download_pdf",
        action="store_false",
        help="Chỉ lấy metadata (tòa án, link PDF), không tải file PDF",
    )
    return ap.parse_args()


if __name__ == "__main__":
    run(parse_args())
