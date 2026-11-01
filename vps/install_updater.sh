#!/usr/bin/env bash
# Cài bộ tự cập nhật độc lập (systemd timer, 10 phút/lần): kéo mã mới từ GitHub, nếu có thay đổi
# thì khởi động lại 2 dịch vụ tải/xử lý. Không phụ thuộc vào việc vòng lặp chính có đang chạy hay không.
set -u
cat > /usr/local/bin/toaan-update <<'EOS'
#!/usr/bin/env bash
cd /root/toaan-scraper || exit 0
old=$(git rev-parse HEAD)
git pull -q --ff-only || exit 0
if [ "$old" != "$(git rev-parse HEAD)" ]; then
  echo "$(date '+%F %T') cập nhật $old -> $(git rev-parse --short HEAD), khởi động lại dịch vụ" >> /root/work/logs/updater.log
  systemctl restart toaan-process toaan-download
fi
EOS
chmod +x /usr/local/bin/toaan-update
cat > /etc/systemd/system/toaan-update.service <<'EOS'
[Unit]
Description=Tu cap nhat ma nguon toaan-scraper
[Service]
Type=oneshot
ExecStart=/usr/local/bin/toaan-update
EOS
cat > /etc/systemd/system/toaan-update.timer <<'EOS'
[Unit]
Description=Tu cap nhat ma nguon toaan-scraper moi 10 phut
[Timer]
OnBootSec=5min
OnUnitActiveSec=10min
[Install]
WantedBy=timers.target
EOS
systemctl daemon-reload
systemctl enable --now toaan-update.timer
echo "Đã cài bộ tự cập nhật (10 phút/lần)."
