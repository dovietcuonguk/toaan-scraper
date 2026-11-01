#!/usr/bin/env bash
# Chuyển rclone sang dùng mã truy cập Google Drive riêng (OAuth Client ID) để tránh bị giới hạn tốc độ chung.
# Cách dùng (đăng nhập VPS bằng: ssh -L 53682:127.0.0.1:53682 root@<IP>):
#   bash /root/toaan-scraper/vps/drive_client.sh '<CLIENT_ID>' '<CLIENT_SECRET>'
set -u
ID="${1:-}"; SECRET="${2:-}"
if [ -z "$ID" ] || [ -z "$SECRET" ]; then
  echo "Thiếu tham số. Cách dùng: bash $0 '<CLIENT_ID>' '<CLIENT_SECRET>'"; exit 1
fi
rclone config update gdrive client_id="$ID" client_secret="$SECRET" >/dev/null
cat <<'TXT'

Sắp hiện câu hỏi và một đường link http://127.0.0.1:53682/auth?state=...
 - Nếu hỏi "Already have a token - refresh?": gõ y rồi Enter
 - Nếu hỏi "Use web browser to automatically authenticate?" (hoặc "Use auto config?"): gõ y rồi Enter
 - Copy đường link dán vào trình duyệt trên MacBook, chọn dovietcuong.uk@gmail.com, bấm Allow
   (nếu Google báo "ứng dụng chưa được xác minh": bấm "Nâng cao" -> "Đi tới ... (không an toàn)")
TXT
rclone config reconnect gdrive: >/dev/null || { echo "LỖI cấp quyền lại. Chạy lại lệnh."; exit 1; }
rclone lsd gdrive: >/dev/null && echo "Kết nối Drive bằng mã riêng: OK" || { echo "LỖI: chưa vào được Drive"; exit 1; }
# Khởi động lại vòng đẩy file để dùng ngay mã mới
pkill -f "rclone move /root/work/staging" ; pkill -f vps/upload_loop.sh
echo "Đã khởi động lại khâu đẩy lên Drive (vòng xử lý sẽ tự bật lại trong vòng 1 phút)."
