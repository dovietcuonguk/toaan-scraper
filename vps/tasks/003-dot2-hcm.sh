#!/usr/bin/env bash
# Việc chạy một lần: chuyển VPS sang đợt 2 (TAND cấp huyện cũ + TAND khu vực của TP. Hồ Chí Minh).
#  - Tắt dịch vụ tải cấp tỉnh (đã xong) để không tải song song từ cùng một địa chỉ IP.
#  - Cài 2 dịch vụ mới: toaan-lower (lấy danh sách + tải PDF) và toaan-upload2 (đẩy PDF thẳng lên BANAN PDF).
#  - Bộ tự cập nhật: khởi động lại đúng dịch vụ có mã nguồn thay đổi.
set -u
REPO=/root/toaan-scraper
WORK=/root/work
echo "$(date '+%F %T') bắt đầu việc 003"
test -f "$WORK/count_lower.json" || { echo "Thiếu $WORK/count_lower.json (việc 002)"; exit 1; }

systemctl disable --now toaan-download.service 2>/dev/null

cat > /etc/systemd/system/toaan-lower.service <<EOF
[Unit]
Description=Dot 2: tai ban an TAND cap huyen / khu vuc TP HCM
After=network-online.target
Wants=network-online.target
[Service]
WorkingDirectory=$REPO
Environment=TOAAN_WORK=$WORK
ExecStart=$REPO/.venv/bin/python -u $REPO/vps/download_lower.py --cities tp-hcm
Restart=on-failure
RestartSec=300
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/toaan-upload2.service <<EOF
[Unit]
Description=Dot 2: day PDF len Google Drive BANAN PDF
After=network-online.target
Wants=network-online.target
[Service]
WorkingDirectory=$REPO
Environment=TOAAN_WORK=$WORK
ExecStart=$REPO/.venv/bin/python -u $REPO/vps/upload_pdf2.py --loop
Restart=always
RestartSec=120
[Install]
WantedBy=multi-user.target
EOF

cat > /usr/local/bin/toaan-update <<'EOS'
#!/usr/bin/env bash
cd /root/toaan-scraper || exit 0
old=$(git rev-parse HEAD)
git pull -q --ff-only || exit 0
new=$(git rev-parse HEAD)
[ "$old" = "$new" ] && exit 0
ch=$(git diff --name-only "$old" "$new")
units="toaan-process"
echo "$ch" | grep -qE '^(scrape_toaan|fetch_pdfs)\.py$|^vps/(download_lower|lower_courts)\.py$' && units="$units toaan-lower"
echo "$ch" | grep -qE '^vps/upload_pdf2\.py$' && units="$units toaan-upload2"
echo "$(date '+%F %T') cập nhật ${old:0:7} -> ${new:0:7}, khởi động lại: $units" >> /root/work/logs/updater.log
systemctl restart $units
EOS
chmod +x /usr/local/bin/toaan-update

systemctl daemon-reload
systemctl enable --now toaan-lower.service toaan-upload2.service
sleep 5
systemctl --no-pager --lines=0 status toaan-lower.service toaan-upload2.service | grep -E "●|Active:"
echo "$(date '+%F %T') xong việc 003"
