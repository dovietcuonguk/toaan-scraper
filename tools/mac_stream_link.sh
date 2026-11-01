#!/usr/bin/env bash
# Chạy trên MacBook NGAY SAU KHI đã đổi Google Drive for Desktop sang "Stream files" (Truyền trực tuyến):
#  - đổi tên thư mục Mirror cũ ~/My Drive → ~/My Drive.bak-mirror (giữ lại để đối chiếu, xoá sau)
#  - tạo liên kết ~/My Drive → thư mục Stream mới, để mọi script/vault Obsidian dùng đường dẫn cũ vẫn chạy
set -eu
ACC="${1:-dovietcuong.uk@gmail.com}"
NEW="$HOME/Library/CloudStorage/GoogleDrive-$ACC/My Drive"
OLD="$HOME/My Drive"
[ -d "$NEW" ] || { echo "Chưa thấy thư mục Stream: $NEW — kiểm tra lại Google Drive đã đổi sang Stream chưa."; exit 1; }
if [ -L "$OLD" ]; then
  echo "~/My Drive đã là liên kết tới: $(readlink "$OLD")"; exit 0
fi
if [ -d "$OLD" ]; then
  [ -e "$OLD.bak-mirror" ] && { echo "Đã có $OLD.bak-mirror — dừng để tránh ghi đè."; exit 1; }
  mv "$OLD" "$OLD.bak-mirror"
  echo "Đã đổi tên thư mục Mirror cũ thành: $OLD.bak-mirror"
fi
ln -s "$NEW" "$OLD"
echo "Đã tạo liên kết: ~/My Drive → $NEW"
ls "$OLD/000 - OBSIDIAN" >/dev/null && echo "Kiểm tra: đọc được ~/My Drive/000 - OBSIDIAN qua liên kết."
