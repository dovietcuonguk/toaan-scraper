#!/usr/bin/env bash
# Đợt 2, phương án A: gom tối đa 2.000 MD đã xong từ /root/work/md2 thành một lô trong /root/work/outbox_md/<lô>
# (giữ nguyên cây thư mục <THÀNH PHỐ>/CAP HUYEN - KHU VUC/<LOẠI>/...) để MacBook kéo về MDBANAN.
# In "<lô> <số file>" của mọi lô đang chờ. MacBook xóa lô sau khi nhận đủ.
set -u
WORK="${TOAAN_WORK:-/root/work}"
SRC="$WORK/md2"; OB="$WORK/outbox_md"
mkdir -p "$SRC" "$OB"
if [ -z "$(ls -A "$OB")" ]; then
  B="md-$(date +%Y%m%d%H%M%S)"; OUT="$OB/$B"; mkdir -p "$OUT"
  cd "$SRC" && find . -type f -name '*.md' ! -name '.*' -mmin +1 | head -2000 | while IFS= read -r f; do
    mkdir -p "$OUT/$(dirname "$f")" && mv "$f" "$OUT/$f"
  done
  [ -z "$(find "$OUT" -type f -print -quit)" ] && rm -rf "$OUT"
fi
for d in "$OB"/*/; do
  [ -d "$d" ] && echo "$(basename "$d") $(find "$d" -type f | wc -l)"
done
true
