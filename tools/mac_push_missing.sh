#!/usr/bin/env bash
# Sau khi Google Drive đã chạy ở chế độ Stream: đưa những file CHỈ CÓ trong bản Mirror cũ (~/My Drive.bak-mirror)
# vào thư mục Stream để Drive tải lên mây. Không ghi đè file đã có trên mây (--ignore-existing).
#
#   bash mac_push_missing.sh "000 - OBSIDIAN/MDBANAN"            # chạy thử: chỉ đếm, không đổi gì
#   bash mac_push_missing.sh "000 - OBSIDIAN/MDBANAN" --that      # làm thật
#   bash mac_push_missing.sh "BANAN PDF" --that
#   bash mac_push_missing.sh "." --that                            # toàn bộ My Drive (chạy sau cùng)
#
# Làm thật: file đã chép sang Stream được xoá khỏi bản Mirror cũ (--remove-source-files) để không tốn gấp đôi ổ;
# bản trong Stream nằm trong bộ nhớ đệm của Drive cho đến khi tải lên xong. Dừng khi ổ còn < 15 GB.
set -u
ACC="${ACC:-dovietcuong.uk@gmail.com}"
BAK="$HOME/My Drive.bak-mirror"
NEW="$HOME/Library/CloudStorage/GoogleDrive-$ACC/My Drive"
REL="${1:?Thiếu thư mục, vd: \"000 - OBSIDIAN/MDBANAN\"}"
MODE="${2:-}"
[ -d "$BAK/$REL" ] || { echo "Không thấy $BAK/$REL"; exit 1; }
[ -d "$NEW" ] && [ ! -L "$NEW" ] || { echo "DỪNG: $NEW chưa phải thư mục Stream (Drive chưa ở chế độ Stream)."; exit 1; }
EXC=(--exclude '.DS_Store' --exclude '._*' --exclude '.*.tmp' --exclude '*.gdoc' --exclude '*.gsheet'
     --exclude '*.gslides' --exclude '*.gform' --exclude '*.gdraw' --exclude '*.gmap' --exclude '*.gsite'
     --exclude 'Icon?' --exclude '.tmp.drivedownload' --exclude '.tmp.driveupload')
mkdir -p "$NEW/$REL"
if [ "$MODE" != "--that" ]; then
  # rsync so khớp cây thư mục nhanh hơn nhiều so với kiểm tra từng file; in danh sách vào ~/toaan-work
  LIST="$HOME/toaan-work/thieu_$(echo "$REL" | tr '/ ' '__').txt"
  mkdir -p "$HOME/toaan-work"
  "$RSYNC" -a --ignore-existing --dry-run --out-format='%n' "${EXC[@]}" "$BAK/$REL/" "$NEW/$REL/" 2>/dev/null \
    | grep -v '/$' > "$LIST"
  n=$(wc -l < "$LIST" | tr -d ' ')
  echo "CHẠY THỬ: \"$REL\": $n file chưa có ở bản Stream (sẽ được đưa lên mây). Danh sách: $LIST"
  [ "$n" -gt 0 ] && { echo "Theo thư mục cấp 1:"; cut -d/ -f1 "$LIST" | sort | uniq -c | sort -rn | head -15; }
  exit 0
fi
free_gb=$(df -g "$HOME" | awk 'NR==2{print $4}')
[ "${free_gb:-0}" -lt 15 ] && { echo "Ổ còn ${free_gb} GB — dừng, chờ Drive tải lên bớt rồi chạy lại."; exit 1; }
echo "$(date '+%F %T') Bắt đầu đưa \"$REL\" lên (ổ còn ${free_gb} GB)…"
rsync -a --ignore-existing --remove-source-files "${EXC[@]}" "$BAK/$REL/" "$NEW/$REL/"
rc=$?
left=$(find "$BAK/$REL" -type f ! -name '.DS_Store' 2>/dev/null | wc -l | tr -d ' ')
echo "$(date '+%F %T') Xong (mã $rc). Còn $left file ở bản cũ (là file đã có sẵn trên mây hoặc file bị loại trừ)."
