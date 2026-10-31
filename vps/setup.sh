#!/usr/bin/env bash
# Cài đặt và khởi động việc tải bản án TAND cấp tỉnh trên VPS (chạy bằng root).
# Phải đăng nhập VPS bằng lệnh có chuyển tiếp cổng 53682 (để cấp quyền Google Drive):
#   ssh -L 53682:127.0.0.1:53682 root@<IP>
# rồi chạy:
#   curl -fsSL https://raw.githubusercontent.com/dovietcuonguk/toaan-scraper/main/vps/setup.sh -o setup.sh && bash setup.sh
set -u
export DEBIAN_FRONTEND=noninteractive
REPO=/root/toaan-scraper
WORK=/root/work
CONGBOBANAN_ID="19QHc6yBgSM_zSSUIhlXAr2JvvNrr9xWp"   # thư mục "000 - OBSIDIAN/CONGBOBANAN" trên Drive

step() { echo; echo "== $* =="; }

step "1/6 Cài phần mềm (OCR tiếng Việt, đọc PDF, rclone)"
apt-get update -qq
apt-get install -y -qq git python3-venv tesseract-ocr tesseract-ocr-vie poppler-utils rclone tmux >/dev/null \
  || { echo "LỖI cài phần mềm"; exit 1; }
tesseract --list-langs 2>/dev/null | grep -q '^vie$' && echo "Tesseract tiếng Việt: OK"
echo "rclone: $(rclone version | head -1)"

step "2/6 Cập nhật mã nguồn"
if [ -d "$REPO/.git" ]; then git -C "$REPO" pull -q --ff-only; else git clone -q https://github.com/dovietcuonguk/toaan-scraper "$REPO"; fi
cd "$REPO"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python -m playwright install chromium >/dev/null 2>&1
curl -fsSL https://raw.githubusercontent.com/dovietcuonguk/toaan-scraper/main/tools/fix_cert_chain.sh | bash
mkdir -p "$WORK"/{data,staging,state,logs}
echo "Mã nguồn: $(git log --oneline -1)"

step "3/6 Kết nối Google Drive"
if rclone lsd gdrive: >/dev/null 2>&1; then
  echo "Đã có kết nối Google Drive từ trước."
else
  cat <<'EOF'
Sắp hiện một đường link dạng http://127.0.0.1:53682/auth?state=...
  1. Copy đường link đó, dán vào trình duyệt trên MacBook.
  2. Chọn tài khoản dovietcuong.uk@gmail.com, bấm "Cho phép" (Allow).
  3. Trình duyệt báo "Success" là xong; quay lại cửa sổ Terminal này.
(Nếu Terminal hỏi thêm câu nào, ví dụ "Shared Drive", cứ gõ n rồi Enter.)
EOF
  rclone config create gdrive drive scope=drive root_folder_id="$CONGBOBANAN_ID" >/dev/null \
    || { echo "LỖI tạo kết nối Drive. Kiểm tra lại đã đăng nhập bằng: ssh -L 53682:127.0.0.1:53682 root@<IP>"; exit 1; }
fi
if ! rclone lsd gdrive: >/dev/null 2>&1; then
  echo "LỖI: chưa truy cập được thư mục CONGBOBANAN trên Drive."; exit 1
fi
echo "Thư mục CONGBOBANAN trên Drive hiện có:"; rclone lsd gdrive: | awk '{print "   " $NF}' | head -15
rclone mkdir "gdrive:TAND CAP TINH"

step "4/6 Kiểm tra dung lượng Drive"
rclone about gdrive: 2>/dev/null | grep -E "Total|Used|Free" || echo "(không đọc được dung lượng)"

step "5/6 Cài dịch vụ chạy nền (tự chạy lại khi máy chủ khởi động lại)"
cat > /etc/systemd/system/toaan-download.service <<EOF
[Unit]
Description=Tai ban an TAND cap tinh (danh sach + PDF)
After=network-online.target
Wants=network-online.target
[Service]
WorkingDirectory=$REPO
Environment=TOAAN_WORK=$WORK
ExecStart=$REPO/.venv/bin/python -u $REPO/vps/download.py
Restart=on-failure
RestartSec=300
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/toaan-process.service <<EOF
[Unit]
Description=Xu ly ban an (OCR, MD) va day len Google Drive
After=network-online.target
Wants=network-online.target
[Service]
WorkingDirectory=$REPO
Environment=TOAAN_WORK=$WORK
ExecStart=/bin/bash $REPO/vps/process_loop.sh
Restart=on-failure
RestartSec=120
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now toaan-download.service toaan-process.service
sleep 5
systemctl --no-pager --lines=0 status toaan-download.service toaan-process.service | grep -E "●|Active:"

step "6/6 XONG"
cat <<EOF
Việc tải đã chạy nền trên máy chủ. Anh có thể đóng Terminal và gập MacBook.
- Xem tiến độ trên Google Drive: CONGBOBANAN/TAND CAP TINH/_TIEN_DO.md (cập nhật 30 phút/lần)
- Xem tiến độ trên máy chủ:      bash $REPO/vps/status.sh
EOF
