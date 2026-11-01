#!/usr/bin/env bash
# Dùng cho chế độ MacBook kéo file về: chuyển một lô file đã xử lý xong từ staging sang outbox/<lô>
# (đổi chỗ trên cùng ổ đĩa, tức thời). In ra "<tên lô> <số file>" của mọi lô đang chờ trong outbox.
set -u
WORK=/root/work
mkdir -p "$WORK/outbox"
touch "$WORK/state/MAC_PULL"
if [ -z "$(ls -A "$WORK/outbox")" ]; then
  B=$(date +%Y%m%d%H%M%S); OUT="$WORK/outbox/$B"; mkdir -p "$OUT"
  cd "$WORK/staging" 2>/dev/null && find . -type f ! -name '*.tmp' -mmin +1 | head -1500 | while IFS= read -r f; do
    mkdir -p "$OUT/$(dirname "$f")" && mv "$f" "$OUT/$f"
  done
  [ -z "$(find "$OUT" -type f -print -quit)" ] && rm -rf "$OUT"
fi
for d in "$WORK"/outbox/*/; do
  [ -d "$d" ] && echo "$(basename "$d") $(find "$d" -type f | wc -l)"
done
