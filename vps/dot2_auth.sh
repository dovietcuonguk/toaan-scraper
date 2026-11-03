#!/usr/bin/env bash
# Đợt 2, phương án A — kết nối rclone với Google Drive bằng OAuth Client ID riêng (dự án banan-rclone).
# Tạo remote "banan" trỏ thẳng thư mục "BANAN PDF". Cần đăng nhập VPS có chuyển tiếp cổng 53682:
#   ssh -t -L 53682:127.0.0.1:53682 root@<IP> 'bash /root/toaan-scraper/vps/dot2_auth.sh'
# (tools/dot2_mac.sh capquyen <1|2|3> làm đúng việc này).
set -u
WORK=/root/work
BANAN_PDF_ID="1hqUh0Mh2bh92zNeoROEMTwlSKIp9BPLT"
J="$WORK/client_secret.json"
[ -s "$J" ] || { echo "THIẾU $J — chạy trước: bash dot2_mac.sh chuanbi"; exit 1; }
read -r ID SECRET < <(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));d=d.get("installed") or d.get("web");print(d["client_id"],d["client_secret"])' "$J") \
  || { echo "Không đọc được $J"; exit 1; }

if rclone lsd banan: >/dev/null 2>&1 && rclone config show banan 2>/dev/null | grep -q "client_id = $ID"; then
  echo "Remote 'banan' đã kết nối bằng Client ID riêng từ trước."
else
  cat <<'TXT'

Sắp hiện một đường link dạng  http://127.0.0.1:53682/auth?state=...
 1. Copy đường link, dán vào trình duyệt trên MacBook.
 2. Chọn tài khoản dovietcuong.uk@gmail.com.
 3. Google báo "Google chưa xác minh ứng dụng này": bấm "Nâng cao" (Advanced) → "Đi tới banan-rclone (không an toàn)".
 4. Bấm "Tiếp tục"/"Cho phép" (Allow). Trình duyệt báo "Success!" là xong, quay lại Terminal.
 (Nếu Terminal hỏi "Configure this as a Shared Drive (Team Drive)?" thì gõ n rồi Enter.)

TXT
  rclone config delete banan >/dev/null 2>&1
  rclone config create banan drive client_id="$ID" client_secret="$SECRET" scope=drive \
      root_folder_id="$BANAN_PDF_ID" >/dev/null \
    || { echo "LỖI tạo kết nối. Kiểm tra đã đăng nhập bằng: ssh -t -L 53682:127.0.0.1:53682 root@<IP>"; exit 1; }
fi
rclone lsd banan: >/dev/null 2>&1 || { echo "LỖI: chưa vào được BANAN PDF trên Drive"; exit 1; }
echo "Thư mục BANAN PDF hiện có:"; rclone lsd banan: | sed 's/^.* -1 /   /' | head -12

echo "Tạo sẵn cây thư mục đợt 2 (tránh 3 máy cùng tạo một thư mục → thư mục trùng tên trên Drive)..."
for city in "TP HO CHI MINH" "HA NOI" "DA NANG"; do
  for t in "01 DAN SU" "02 HINH SU" "03 KINH DOANH THUONG MAI" "04 HON NHAN GIA DINH" "05 LAO DONG" \
           "06 PHA SAN" "07 HANH CHINH" "08 XU LY HANH CHINH" "09 KHAC"; do
    rclone mkdir "banan:$city/CAP HUYEN - KHU VUC/$t/_CHUA DAT TEN" 2>/dev/null
  done
done
rclone mkdir "banan:_BAO_CAO/DOT2" 2>/dev/null
date -Iseconds > "$WORK/state/AUTH_OK"
echo "KẾT NỐI DRIVE: OK"
