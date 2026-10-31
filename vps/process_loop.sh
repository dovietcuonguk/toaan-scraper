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

last_report=0
while true; do
  out=$("$PY" "$REPO/vps/process.py" --data-dir "$WORK/data" --staging-dir "$STAGING" \
          --state-dir "$WORK/state" --batch 300 2>&1)
  echo "$(date '+%F %T') $out" | tail -3 >> "$LOG"

  # Đẩy kết quả lên Drive; file chỉ bị xoá khỏi máy chủ sau khi đã lên Drive thành công
  if [ -n "$(find "$STAGING" -type f -print -quit)" ]; then
    rclone move "$STAGING" "$REMOTE" "${RCLONE_OPTS[@]}" --delete-empty-src-dirs
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
    date -Iseconds > "$WORK/ALL_DONE"
    "$PY" "$REPO/vps/progress.py" > "$WORK/TIEN_DO.md"
    rclone copyto "$WORK/TIEN_DO.md" "$DEST/_TIEN_DO.md" "${RCLONE_OPTS[@]}"
    echo "$(date '+%F %T') HOÀN TẤT TOÀN BỘ" >> "$LOG"
    exit 0
  fi
  echo "$out" | grep -q "Không có bản ghi mới" && sleep 120
done
