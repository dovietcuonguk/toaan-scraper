#!/usr/bin/env bash
# Đợt 2, phương án A — cài đặt một VPS (chạy bằng root, không cần tương tác). tools/dot2_mac.sh chuanbi gọi script này.
# Không đụng tới dữ liệu đợt 1 (/root/work/data, staging) nếu có.
set -u
export DEBIAN_FRONTEND=noninteractive
REPO=/root/toaan-scraper
WORK=/root/work
step() { echo "== $* =="; }

step "1/5 Cài phần mềm (git, python, poppler, rclone)"
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq git python3-venv poppler-utils rclone curl ca-certificates >/dev/null 2>&1 \
  || { echo "LỖI cài phần mềm"; exit 1; }
echo "rclone: $(rclone version | head -1)"

step "2/5 Mã nguồn + môi trường Python + Chromium"
if [ -d "$REPO/.git" ]; then git -C "$REPO" pull -q --ff-only; else git clone -q https://github.com/dovietcuonguk/toaan-scraper "$REPO"; fi
cd "$REPO" || exit 1
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt || { echo "LỖI pip"; exit 1; }
.venv/bin/python -m playwright install chromium >/dev/null 2>&1
if ! .venv/bin/python - <<'PY' >/dev/null 2>&1
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    p.chromium.launch().close()
PY
then
  echo "Chromium thiếu thư viện hệ thống — cài bổ sung"
  .venv/bin/python -m playwright install-deps chromium >/dev/null 2>&1
fi
.venv/bin/python - <<'PY' && echo "Chromium: OK" || { echo "LỖI: Chromium không chạy được"; exit 1; }
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    p.chromium.launch().close()
PY
bash tools/fix_cert_chain.sh || echo "(cảnh báo: chưa thêm được chứng chỉ trung gian)"
mkdir -p "$WORK"/{state,logs,data2,md2,upload2,outbox_md}
echo "Mã nguồn: $(git log --oneline -1)"

step "3/5 Kiểm tra file chuẩn bị"
ok=1
[ -s "$WORK/count_lower.json" ] && echo "count_lower.json: OK" || { echo "THIẾU $WORK/count_lower.json"; ok=0; }
[ -s "$WORK/client_secret.json" ] && chmod 600 "$WORK/client_secret.json" && echo "client_secret.json: OK" \
  || { echo "THIẾU $WORK/client_secret.json"; ok=0; }

step "4/5 Tắt dịch vụ cũ (đợt 1, phương án B)"
for s in toaan-download toaan-process toaan-lower toaan-upload2; do systemctl disable --now "$s" 2>/dev/null; done
mkdir -p "$WORK/state/tasks_done"; touch "$WORK/state/tasks_done/003-dot2-hcm.sh"
echo "đã tắt"

step "5/5 Bộ tự cập nhật mã nguồn (10 phút/lần)"
cat > /usr/local/bin/toaan-update <<'EOS'
#!/usr/bin/env bash
cd /root/toaan-scraper || exit 0
old=$(git rev-parse HEAD)
git pull -q --ff-only || exit 0
new=$(git rev-parse HEAD)
[ "$old" = "$new" ] && exit 0
ch=$(git diff --name-only "$old" "$new")
units=""
echo "$ch" | grep -qE '^(scrape_toaan|fetch_pdfs)\.py$|^vps/(download_lower|lower_courts)\.py$' && units="$units toaan-lower"
echo "$ch" | grep -qE '^vps/(process2|process|lower_courts)\.py$|^mac/frontmatter\.py$' && units="$units toaan-process2"
echo "$ch" | grep -qE '^vps/(upload3\.sh|dot2_status\.py)$' && units="$units toaan-upload3"
act=""
for u in $units; do systemctl is-active -q "$u" && act="$act $u"; done
echo "$(date '+%F %T') cập nhật ${old:0:7} -> ${new:0:7}; khởi động lại:${act:- (không)}" >> /root/work/logs/updater.log
[ -n "$act" ] && systemctl restart $act
exit 0
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
systemctl enable --now toaan-update.timer >/dev/null 2>&1
echo "toaan-update.timer: $(systemctl is-active toaan-update.timer)"

[ "$ok" = 1 ] && echo "CÀI ĐẶT XONG" || { echo "CÀI ĐẶT XONG NHƯNG THIẾU FILE (xem trên)"; exit 2; }
