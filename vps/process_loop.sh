#!/usr/bin/env bash
# Vòng lặp xử lý: trích văn bản/OCR → tạo MD → đẩy PDF + MD lên Google Drive (CONGBOBANAN)
# → cập nhật file tiến độ trên Drive. Dừng khi việc tải đã xong và không còn gì để xử lý.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${TOAAN_WORK:-/root/work}"
PY="$REPO/.venv/bin/python"
STAGING="$WORK/staging"
REMOTE="gdrive:"            # gốc của remote = thư mục CONGBOBANAN trên Drive
DEST="${REMOTE}TAND CAP TINH"
LOG="$WORK/logs/process.log"
mkdir -p "$STAGING" "$WORK/logs" "$WORK/state"
RCLONE_OPTS=(--transfers 4 --checkers 8 --tpslimit 8 --retries 5 --low-level-retries 10
             --log-file "$WORK/logs/rclone.log" --log-level NOTICE)

ensure_uploader() {
  # Đẩy file lên Drive do vòng upload_loop.sh chạy song song đảm nhận; bật lại nếu chưa chạy
  local pid; pid=$(cat "$WORK/state/upload_loop.pid" 2>/dev/null)
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    nohup /bin/bash "$REPO/vps/upload_loop.sh" >> "$WORK/logs/upload.log" 2>&1 &
    echo "$(date '+%F %T') khởi động vòng đẩy file lên Drive" >> "$LOG"
  fi
}

last_report=0
while true; do
  # Tự cập nhật mã nguồn; nếu có bản mới thì chạy lại chính script này (bản mới)
  old=$(git -C "$REPO" rev-parse HEAD); git -C "$REPO" pull -q --ff-only 2>/dev/null
  if [ "$old" != "$(git -C "$REPO" rev-parse HEAD)" ]; then
    echo "$(date '+%F %T') cập nhật mã nguồn, khởi động lại vòng xử lý" >> "$LOG"; exec /bin/bash "$0"
  fi
  # Giữ hàng chờ đẩy lên Drive vừa phải (tối đa ~3000 file) để khâu xử lý không chiếm hết ổ đĩa
  ensure_uploader
  while [ "$(find "$STAGING" -type f | wc -l)" -gt 3000 ]; do ensure_uploader; sleep 60; done
  out=$("$PY" "$REPO/vps/process.py" --data-dir "$WORK/data" --staging-dir "$STAGING" \
          --state-dir "$WORK/state" --batch 300 2>&1)
  echo "$(date '+%F %T') $out" | tail -3 >> "$LOG"


  # Một lần: đặt lại tên các bản án trong CHUA DAT TEN (sau khi sửa cách đọc số/ngày)
  if [ ! -f "$WORK/state/names_fixed_v1" ] && [ -z "$(find "$STAGING" -type f -print -quit)" ]; then
    "$PY" "$REPO/vps/fix_names.py" >> "$LOG" 2>&1 && touch "$WORK/state/names_fixed_v1"
  fi

  now=$(date +%s)
  if [ $((now - last_report)) -ge 1800 ] || [ -f "$WORK/DOWNLOAD_DONE" ]; then
    "$PY" "$REPO/vps/progress.py" > "$WORK/TIEN_DO.md" 2>>"$LOG"
    rclone copyto "$WORK/TIEN_DO.md" "$DEST/_TIEN_DO.md" "${RCLONE_OPTS[@]}"
    # Sao lưu metadata (records_full.jsonl) để công cụ tra cứu trên MacBook đọc được
    rclone copy "$WORK/data" "$DEST/_METADATA" --include "**/records_full.jsonl" "${RCLONE_OPTS[@]}"
    last_report=$now
  fi

  if [ -f "$WORK/DOWNLOAD_DONE" ] && echo "$out" | grep -q "Không có bản ghi mới" \
     && [ -z "$(find "$STAGING" -type f -print -quit)" ]; then
    kill "$(cat "$WORK/state/upload_loop.pid" 2>/dev/null)" 2>/dev/null
    date -Iseconds > "$WORK/ALL_DONE"
    "$PY" "$REPO/vps/progress.py" > "$WORK/TIEN_DO.md"
    rclone copyto "$WORK/TIEN_DO.md" "$DEST/_TIEN_DO.md" "${RCLONE_OPTS[@]}"
    echo "$(date '+%F %T') HOÀN TẤT TOÀN BỘ" >> "$LOG"
    exit 0
  fi
  echo "$out" | grep -q "Không có bản ghi mới" && sleep 120
done
