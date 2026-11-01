#!/usr/bin/env bash
# Chạy trên MacBook (thay mac_pull.sh): VPS chỉ tải PDF; MacBook kéo PDF thô về, OCR + tạo MD tại chỗ,
# ghi thẳng vào cấu trúc mới:
#   MD : ~/My Drive/000 - OBSIDIAN/MDBANAN/<THÀNH PHỐ>/CAP TINH/<LOẠI>/
#   PDF: ~/My Drive/BANAN PDF/<THÀNH PHỐ>/CAP TINH/<LOẠI>/
# Bản án VPS đã xử lý từ trước (còn trong staging) vẫn kéo về chỗ cũ CONGBOBANAN/TAND CAP TINH như mac_pull.sh.
#   caffeinate -is bash ~/Developer/toaan-scraper-v2/tools/mac_process.sh
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
VPS="root@14.225.215.198"
GD="$HOME/My Drive"
OLD_DEST="$GD/000 - OBSIDIAN/CONGBOBANAN"
MD_ROOT="$GD/000 - OBSIDIAN/MDBANAN"
PDF_ROOT="$GD/BANAN PDF"
WORKM="$HOME/toaan-work"; INBOX="$WORKM/inbox"; STATE="$WORKM/state"
MIN_FREE_GB=${MIN_FREE_GB:-20}
SSH=(ssh -o BatchMode=yes -o ServerAliveInterval=30 -o ConnectTimeout=20 "$VPS")
PY=python3

mkdir -p "$INBOX" "$STATE" "$MD_ROOT" "$PDF_ROOT"
for t in tesseract pdftotext pdftoppm pdfinfo; do command -v $t >/dev/null || { echo "Thiếu $t (brew install tesseract tesseract-lang poppler)"; exit 1; }; done
"${SSH[@]}" true || { echo "Chưa đăng nhập VPS được bằng khóa SSH."; exit 1; }
"${SSH[@]}" 'cd /root/toaan-scraper && git pull -q; touch /root/work/state/MAC_PULL /root/work/state/MAC_PROCESS; pkill -f vps/process.py; pkill -f "rclone move /root/work/staging"; true'
echo "$(date '+%F %T') Bắt đầu. MD → $MD_ROOT | PDF → $PDF_ROOT"

process_inbox() {
  for d in "$INBOX"/raw-*/; do
    [ -d "$d" ] || continue
    b=$(basename "$d"); t0=$(date +%s)
    "$PY" "$REPO/mac/process_inbox.py" --inbox "$d" --md-root "$MD_ROOT" --pdf-root "$PDF_ROOT" --state-dir "$STATE" \
      2>>"$WORKM/process_errors.log" | tail -1
    sent=$(cat "$d/.sent" 2>/dev/null || echo 1); lines=$(wc -l < "$d/_done.csv" 2>/dev/null | tr -d ' ')
    if [ -f "$d/_done.csv" ] && tail -n +$((sent + 1)) "$d/_done.csv" | "${SSH[@]}" 'cat >> /root/work/state/processed_mac.csv'; then
      echo "$lines" > "$d/.sent"
      left=$(find "$d/pdf" -type f 2>/dev/null | wc -l | tr -d ' ')
      if [ "$left" = "0" ]; then rm -rf "$d"; else echo "  Lô $b còn $left PDF chưa xử lý — giữ lại để chạy lại"; fi
      echo "  (lô $b: $(( $(date +%s) - t0 )) giây)"
    fi
  done
}

total=0
while true; do
  process_inbox
  free_gb=$(df -g "$HOME" | awk 'NR==2{print $4}')
  if [ "${free_gb:-0}" -lt "$MIN_FREE_GB" ]; then
    echo "$(date '+%F %T') MacBook còn ${free_gb} GB trống — chờ 10 phút cho Google Drive đồng bộ bớt"
    sleep 600; continue
  fi
  batches=$("${SSH[@]}" 'bash /root/toaan-scraper/vps/outbox.sh >/dev/null 2>&1; /root/toaan-scraper/.venv/bin/python /root/toaan-scraper/vps/outbox_raw.py --make; for d in /root/work/outbox/*/; do [ -d "$d" ] && echo "$(basename "$d") $(find "$d" -type f | wc -l)"; done' 2>/dev/null)
  if [ -z "$batches" ]; then
    echo "$(date '+%F %T') Chưa có file mới. Đã nhận tổng cộng: $total file."
    "${SSH[@]}" 'grep -E "^Hoàn thành" /root/work/TIEN_DO.md 2>/dev/null' || true
    "${SSH[@]}" 'test -f /root/work/ALL_DONE' && { echo "VPS đã xong toàn bộ."; exit 0; }
    sleep 300; continue
  fi
  while read -r b n; do
    [ -z "$b" ] && continue
    case "$b" in raw-*) dest="$INBOX/$b";; *) dest="$OLD_DEST";; esac
    mkdir -p "$dest"
    got=$("${SSH[@]}" "tar -C /root/work/outbox/$b -cf - ." | tar -C "$dest" -xvf - 2>&1 | grep '^x ' | grep -vc '/$')
    if [ "$got" -ge "$n" ]; then
      "${SSH[@]}" "rm -rf /root/work/outbox/$b"
      total=$((total + n))
      echo "$(date '+%F %T') Lô $b: đã nhận $n file (tổng $total)"
    else
      echo "$(date '+%F %T') Lô $b: chỉ nhận $got/$n file — sẽ kéo lại"
      case "$b" in raw-*) rm -rf "$dest";; esac
      sleep 30
    fi
  done <<< "$batches"
done
