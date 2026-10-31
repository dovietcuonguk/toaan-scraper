#!/usr/bin/env bash
# Chạy thử trên VPS Việt Nam (Ubuntu 22.04/24.04), chạy bằng quyền root:
#   curl -fsSL https://raw.githubusercontent.com/dovietcuonguk/toaan-scraper/main/tools/vps_test.sh | bash
# Bước 1: kiểm tra cổng congbobanan có cho IP này truy cập không.
# Bước 2 (nếu truy cập được): cài trình duyệt Chromium và đếm số bản án của
#         TAND cấp tỉnh TP. Hồ Chí Minh, Hà Nội, Đà Nẵng. Không tải bản án nào.
set -u
URL="https://congbobanan.toaan.gov.vn/0tat1cvn/ban-an-quyet-dinh"

echo "== Thông tin máy chủ =="
curl -s --max-time 10 https://ipinfo.io/json | grep -E '"(ip|city|region|country|org)"' || true

echo
echo "== Bước 1: kiểm tra truy cập cổng congbobanan =="
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 -A "Mozilla/5.0" "$URL")
echo "Mã phản hồi HTTP: $code"
if [ "$code" != "200" ]; then
  echo "KẾT LUẬN: KHÔNG truy cập được cổng từ máy chủ này (mã $code). Dừng chạy thử."
  exit 1
fi
echo "KẾT LUẬN BƯỚC 1: TRUY CẬP ĐƯỢC."

echo
echo "== Bước 2: cài đặt (khoảng 3-5 phút) =="
# Máy chạy thử chỉ có 2 GB RAM: thêm 2 GB bộ nhớ ảo (swap) để Chromium không bị thiếu RAM.
mem_kb=$(awk '/MemTotal/{print $2}' /proc/meminfo)
if [ "$mem_kb" -lt 3500000 ] && ! swapon --show | grep -q swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  echo "Đã thêm 2 GB swap."
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git python3-venv python3-pip >/dev/null
rm -rf ~/toaan-scraper
git clone -q --depth 1 https://github.com/dovietcuonguk/toaan-scraper ~/toaan-scraper
cd ~/toaan-scraper
python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python -m playwright install --with-deps chromium >/dev/null 2>&1
echo "Cài đặt xong."

echo
echo "== Bước 3: đếm số bản án 3 Tòa x 8 loại vụ việc (khoảng 15-30 phút) =="
python -u tools/count_courts.py
