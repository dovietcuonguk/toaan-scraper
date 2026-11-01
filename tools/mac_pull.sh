#!/usr/bin/env bash
# Chạy trên MacBook: kéo bản án đã xử lý (PDF + MD) từ VPS về thư mục CONGBOBANAN trong Google Drive
# trên máy; Google Drive cho máy tính tự đồng bộ lên mây. Để cửa sổ Terminal mở, MacBook cắm sạc.
#   caffeinate -is bash ~/mac_pull.sh
set -u
VPS="root@14.225.215.198"
DEST="$HOME/My Drive/000 - OBSIDIAN/CONGBOBANAN"
SSH=(ssh -o BatchMode=yes -o ServerAliveInterval=30 -o ConnectTimeout=20 "$VPS")

[ -d "$DEST" ] || { echo "Không thấy thư mục: $DEST"; exit 1; }
"${SSH[@]}" true || { echo "Chưa đăng nhập VPS được bằng khóa SSH (chạy ssh-copy-id $VPS trước)."; exit 1; }
"${SSH[@]}" 'cd /root/toaan-scraper && git pull -q; touch /root/work/state/MAC_PULL; pkill -f "rclone move /root/work/staging"; pkill -f vps/upload_loop.sh; true'
echo "$(date '+%F %T') Bắt đầu kéo file về: $DEST"

total=0
while true; do
  free_gb=$(df -g "$HOME" | awk 'NR==2{print $4}')
  if [ "${free_gb:-0}" -lt 15 ]; then
    echo "$(date '+%F %T') MacBook còn ${free_gb} GB trống — chờ 10 phút cho Google Drive đồng bộ bớt"
    sleep 600; continue
  fi
  batches=$("${SSH[@]}" 'bash /root/toaan-scraper/vps/outbox.sh' 2>/dev/null)
  if [ -z "$batches" ]; then
    echo "$(date '+%F %T') Chưa có file mới. Đã kéo về tổng cộng: $total file."
    "${SSH[@]}" 'grep -E "^Hoàn thành|Trạng thái|ĐÃ HOÀN TẤT" /root/work/TIEN_DO.md 2>/dev/null' || true
    "${SSH[@]}" 'test -f /root/work/ALL_DONE' && { echo "VPS đã xong toàn bộ."; exit 0; }
    sleep 300; continue
  fi
  while read -r b n; do
    [ -z "$b" ] && continue
    got=$("${SSH[@]}" "tar -C /root/work/outbox/$b -cf - ." | tar -C "$DEST" -xvf - 2>&1 | grep '^x ' | grep -vc '/$')
    if [ "$got" -ge "$n" ]; then
      "${SSH[@]}" "rm -rf /root/work/outbox/$b"
      total=$((total + n))
      echo "$(date '+%F %T') Lô $b: đã kéo $n file (tổng $total)"
    else
      echo "$(date '+%F %T') Lô $b: chỉ nhận $got/$n file — sẽ kéo lại"
      sleep 30
    fi
  done <<< "$batches"
done
