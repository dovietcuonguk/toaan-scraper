#!/usr/bin/env bash
# Đợt 2, phương án A — khởi động một VPS theo nhóm Tòa của máy.
#   bash /root/toaan-scraper/vps/dot2_start.sh <1|2|3> [--test]
#   --test : chỉ tải một Tòa nhỏ trong nhóm (ưu tiên TAND huyện Cần Giờ) để kiểm tra tên file, YAML, Drive.
# Ba dịch vụ: toaan-lower (danh sách + PDF), toaan-process2 (tên + MD), toaan-upload3 (đẩy PDF lên BANAN PDF).
set -u
REPO=/root/toaan-scraper
WORK=/root/work
K="${1:-}"; MODE="${2:-}"
case "$K" in 1|2|3) ;; *) echo "Cách dùng: bash $0 <1|2|3> [--test]"; exit 1;; esac
TEST=""; [ "$MODE" = "--test" ] && TEST="--test"

[ -s "$WORK/count_lower.json" ] || { echo "THIẾU $WORK/count_lower.json"; exit 1; }
rclone lsd banan: >/dev/null 2>&1 || { echo "Chưa kết nối Drive (remote banan). Chạy: bash dot2_mac.sh capquyen $K"; exit 1; }
git -C "$REPO" fetch -q origin main 2>/dev/null && git -C "$REPO" reset -q --hard origin/main
echo "$K" > "$WORK/dot2_vps"
mkdir -p "$WORK"/{state,logs,data2,md2,upload2,outbox_md}
for s in toaan-download toaan-process toaan-upload2; do systemctl disable --now "$s" 2>/dev/null; done
mkdir -p "$WORK/state/tasks_done"; touch "$WORK/state/tasks_done/003-dot2-hcm.sh"
if [ -z "$TEST" ]; then rm -f "$WORK/DOWNLOAD2_DONE" "$WORK/DOT2_ALL_DONE"; fi

unit() {  # tên, mô tả, lệnh, chính sách Restart
  cat > "/etc/systemd/system/$1.service" <<EOF
[Unit]
Description=$2
After=network-online.target
Wants=network-online.target
[Service]
WorkingDirectory=$REPO
Environment=TOAAN_WORK=$WORK
ExecStart=$3
Restart=$4
RestartSec=120
[Install]
WantedBy=multi-user.target
EOF
}
unit toaan-lower "Dot 2 (VPS$K): danh sach + PDF TAND cap huyen / khu vuc" \
  "$REPO/.venv/bin/python -u $REPO/vps/download_lower.py --shard $K/3 $TEST" on-failure
unit toaan-process2 "Dot 2 (VPS$K): dat ten + tao MD" "$REPO/.venv/bin/python -u $REPO/vps/process2.py --loop" always
unit toaan-upload3 "Dot 2 (VPS$K): day PDF len BANAN PDF" "/bin/bash $REPO/vps/upload3.sh" always
systemctl daemon-reload
systemctl enable toaan-lower toaan-process2 toaan-upload3 >/dev/null 2>&1
systemctl restart toaan-lower toaan-process2 toaan-upload3
sleep 8
echo "VPS$K${TEST:+ (CHẠY THỬ)}:"
for s in toaan-lower toaan-process2 toaan-upload3 toaan-update.timer; do echo "  $s: $(systemctl is-active $s)"; done
"$REPO/.venv/bin/python" "$REPO/vps/lower_courts.py" "$WORK/count_lower.json" 3 | sed -n "1p;$((K + 1))p"
tail -3 "$WORK/logs/download2.log" 2>/dev/null
