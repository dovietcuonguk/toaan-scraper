#!/usr/bin/env bash
# Vòng đẩy file lên Google Drive, chạy song song với khâu xử lý (process_loop.sh khởi động vòng này).
# Đẩy liên tục mọi file trong staging; file chỉ bị xoá khỏi máy chủ sau khi đã lên Drive thành công.
set -u
WORK="${TOAAN_WORK:-/root/work}"
STAGING="$WORK/staging"
echo $$ > "$WORK/state/upload_loop.pid"
while true; do
  if [ -n "$(find "$STAGING" -type f -mmin +1 -print -quit)" ]; then
    # --no-traverse: không liệt kê lại hàng nghìn file đã có trên Drive mỗi lần đẩy
    # --min-age 1m: không đẩy file vừa được ghi (tránh đẩy MD đang ghi dở)
    rclone move "$STAGING" "gdrive:" --no-traverse --min-age 1m \
      --transfers 8 --checkers 16 --tpslimit 10 --tpslimit-burst 20 \
      --retries 5 --low-level-retries 20 --delete-empty-src-dirs \
      --log-file "$WORK/logs/rclone.log" --log-level NOTICE --stats 5m --stats-one-line \
      --stats-log-level NOTICE
  else
    sleep 30
  fi
done
