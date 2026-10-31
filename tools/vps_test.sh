#!/usr/bin/env bash
# Chạy thử trên VPS Việt Nam (Ubuntu), chạy bằng quyền root:
#   curl -fsSL https://raw.githubusercontent.com/dovietcuonguk/toaan-scraper/main/tools/vps_test.sh | bash
# Bước 1: kiểm tra cổng congbobanan có cho IP này truy cập không (sửa lỗi chuỗi chứng chỉ trước).
# Bước 2: cài trình duyệt Chromium và thư viện.
# Bước 3: đếm số bản án của TAND cấp tỉnh TP. Hồ Chí Minh, Hà Nội, Đà Nẵng. Không tải bản án nào.
set -u
REPO_RAW="https://raw.githubusercontent.com/dovietcuonguk/toaan-scraper/main"
URL="https://congbobanan.toaan.gov.vn/0tat1cvn/ban-an-quyet-dinh"
export DEBIAN_FRONTEND=noninteractive

echo "== Thông tin máy chủ =="
curl -s --max-time 10 https://ipinfo.io/json | grep -E '"(ip|city|country|org)"' || true
grep PRETTY_NAME /etc/os-release

echo
echo "== Bước 1: sửa chuỗi chứng chỉ và kiểm tra truy cập cổng congbobanan =="
curl -fsSL "$REPO_RAW/tools/fix_cert_chain.sh" | bash
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 -A "Mozilla/5.0" "$URL")
echo "Mã phản hồi HTTP (có kiểm tra chứng chỉ): $code"
if [ "$code" != "200" ]; then
  code_k=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 60 -A "Mozilla/5.0" "$URL")
  echo "Mã phản hồi HTTP (bỏ qua chứng chỉ): $code_k"
  if [ "$code_k" != "200" ]; then
    echo "KẾT LUẬN: KHÔNG truy cập được cổng từ máy chủ này. Dừng chạy thử."
    exit 1
  fi
  echo "Lưu ý: chỉ truy cập được khi bỏ qua kiểm tra chứng chỉ; vẫn chạy tiếp."
fi
echo "KẾT LUẬN BƯỚC 1: TRUY CẬP ĐƯỢC."

echo
echo "== Bước 2: cài đặt (khoảng 3-8 phút) =="
mem_kb=$(awk '/MemTotal/{print $2}' /proc/meminfo)
if [ "$mem_kb" -lt 3500000 ] && ! swapon --show | grep -q swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  echo "Đã thêm 2 GB swap."
fi
apt-get update -qq
apt-get install -y -qq git python3-venv python3-pip >/dev/null || { echo "LỖI cài git/python"; exit 1; }
rm -rf ~/toaan-scraper
git clone -q --depth 1 https://github.com/dovietcuonguk/toaan-scraper ~/toaan-scraper
cd ~/toaan-scraper
python3 -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt || { echo "LỖI cài thư viện Python"; exit 1; }
if ! python -m playwright install --with-deps chromium >/tmp/pw_install.log 2>&1; then
  echo "Cài thư viện hệ thống cho Chromium theo cách dự phòng..."
  apt-get install -y -qq libnss3 libnspr4 libdbus-1-3 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libxshmfence1 \
    fonts-liberation fonts-noto-core >/dev/null 2>&1
  for p in libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libasound2t64 libatspi2.0-0t64 \
           libatk1.0-0 libatk-bridge2.0-0 libcups2 libasound2 libatspi2.0-0; do
    apt-get install -y -qq "$p" >/dev/null 2>&1 || true
  done
  python -m playwright install chromium >>/tmp/pw_install.log 2>&1 || { tail -20 /tmp/pw_install.log; echo "LỖI cài Chromium"; exit 1; }
fi
python - <<'EOF' || { echo "LỖI: Chromium không khởi động được"; tail -20 /tmp/pw_install.log; exit 1; }
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); b.close()
print("Chromium khởi động được.")
EOF
echo "Cài đặt xong."

echo
echo "== Bước 3: đếm số bản án 3 Tòa x 8 loại vụ việc (khoảng 15-30 phút) =="
python -u tools/count_courts.py
