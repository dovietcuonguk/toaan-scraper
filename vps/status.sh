#!/usr/bin/env bash
# Xem nhanh tiến độ tải bản án trên VPS.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
export TOAAN_WORK="${TOAAN_WORK:-/root/work}"
systemctl --no-pager --lines=0 status toaan-download.service toaan-process.service 2>/dev/null | grep -E "●|Active:"
echo
"$REPO/.venv/bin/python" "$REPO/vps/progress.py"
echo
echo "--- 5 dòng cuối nhật ký xử lý ---"
tail -5 "$TOAAN_WORK/logs/process.log" 2>/dev/null
