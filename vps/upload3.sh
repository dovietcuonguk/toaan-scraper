#!/usr/bin/env bash
# Đợt 2, phương án A (dịch vụ toaan-upload3): đẩy PDF đã đặt tên từ /root/work/upload2 lên Google Drive
# "BANAN PDF" (remote rclone "banan", Client ID riêng), xóa khỏi VPS sau khi lên Drive; 30 phút/lần
# ghi tiến độ của máy lên BANAN PDF/_TIEN_DO_DOT2/TIEN_DO_VPS<k>.md.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${TOAAN_WORK:-/root/work}"
K="$(cat "$WORK/dot2_vps" 2>/dev/null || echo 0)"
UP="$WORK/upload2"
LOG="$WORK/logs/upload3.log"
mkdir -p "$UP" "$WORK/logs"
OPTS=(--min-age 30s --transfers 4 --checkers 4 --tpslimit 4 --no-traverse
      --retries 5 --low-level-retries 10 --log-file "$WORK/logs/rclone3.log" --log-level NOTICE)
last=0
while true; do
  n=$(find "$UP" -type f -name '*.pdf' | wc -l)
  if [ "$n" -gt 0 ]; then
    t0=$(date +%s)
    rclone move "$UP" banan: "${OPTS[@]}"; rc=$?
    left=$(find "$UP" -type f -name '*.pdf' | wc -l)
  # Dọn thư mục rỗng đã lâu (không xóa thư mục process2 vừa tạo, tránh lỗi "No such file")
  find "$UP" -mindepth 1 -type d -empty -mmin +30 -delete 2>/dev/null
    echo "$(date '+%F %T') đẩy $((n - left))/$n PDF trong $(( $(date +%s) - t0 ))s (mã $rc), còn $left" >> "$LOG"
  fi
  left=$(find "$UP" -type f -name '*.pdf' | wc -l)
  # Dọn thư mục rỗng đã lâu (không xóa thư mục process2 vừa tạo, tránh lỗi "No such file")
  find "$UP" -mindepth 1 -type d -empty -mmin +30 -delete 2>/dev/null
  now=$(date +%s)
  if [ $((now - last)) -ge 1800 ]; then
    "$REPO/.venv/bin/python" "$REPO/vps/dot2_status.py" > "$WORK/TIEN_DO_DOT2_VPS.md" 2>>"$LOG"
    rclone copyto "$WORK/TIEN_DO_DOT2_VPS.md" "banan:_TIEN_DO_DOT2/TIEN_DO_VPS${K}.md" --log-level ERROR >> "$LOG" 2>&1
    last=$now
  fi
  # Xong toàn bộ: đã tải xong, không còn PDF chờ xử lý / chờ đẩy
  if [ -f "$WORK/DOWNLOAD2_DONE" ] && [ "$left" = "0" ] && ! systemctl is-active -q toaan-taibu; then
    pending=$("$REPO/.venv/bin/python" "$REPO/vps/dot2_status.py" --pending 2>/dev/null || echo 1)
    [ "$pending" = "0" ] && [ ! -f "$WORK/DOT2_ALL_DONE" ] && date -Iseconds > "$WORK/DOT2_ALL_DONE" \
      && echo "$(date '+%F %T') ĐÃ XONG đợt 2 trên máy này" >> "$LOG"
  fi
  sleep 60
done
