#!/usr/bin/env bash
# Đợt 2, phương án A — điều khiển 3 VPS từ MacBook. Tải về một lần:
#   curl -fsSL https://raw.githubusercontent.com/dovietcuonguk/toaan-scraper/main/tools/dot2_mac.sh -o ~/dot2_mac.sh
# Các lệnh (chạy lần lượt):
#   bash ~/dot2_mac.sh chuanbi        chép count_lower.json + client_secret.json lên 3 máy, cài đặt (5–10 phút, không cần thao tác)
#   bash ~/dot2_mac.sh capquyen 1     cấp quyền Google Drive cho VPS1 (mở link trong trình duyệt) — làm tương tự với 2, 3
#   bash ~/dot2_mac.sh chia           xem nhóm Tòa của từng máy
#   bash ~/dot2_mac.sh thu            chạy thử trên VPS1 (một Tòa nhỏ, ưu tiên TAND huyện Cần Giờ)
#   bash ~/dot2_mac.sh chay           chạy chính thức cả 3 máy
#   bash ~/dot2_mac.sh tiendo         xem tiến độ 3 máy
#   bash ~/dot2_mac.sh theodoi [giây]  màn hình theo dõi thời gian thực cả 3 máy (mặc định 30 giây/lần)
#   caffeinate -is bash ~/dot2_mac.sh keo    kéo MD về MDBANAN (để Terminal mở, MacBook cắm sạc)
#   bash ~/dot2_mac.sh suaten         đổi lại tên file đã xử lý theo quy tắc mới (Drive + VPS + Mac)
#   bash ~/dot2_mac.sh dung           dừng tải trên cả 3 máy (khẩn cấp)
set -u
HOSTS=("${VPS1:-14.225.215.198}" "${VPS2:-103.153.75.234}" "${VPS3:-103.153.75.147}")
SECRET_JSON="${SECRET_JSON:-$HOME/.config/banan-rclone/client_secret.json}"
MD_ROOT="${MD_ROOT:-$HOME/My Drive/000 - OBSIDIAN/MDBANAN}"
RAW=https://raw.githubusercontent.com/dovietcuonguk/toaan-scraper/main
LOGD="$HOME/toaan-dot2-logs"; mkdir -p "$LOGD"
R=/root/toaan-scraper
sshq() { ssh -o BatchMode=yes -o ServerAliveInterval=30 -o ConnectTimeout=20 "root@$1" "${@:2}"; }
host() { case "$1" in 1|2|3) echo "${HOSTS[$(($1 - 1))]}";; *) echo "Số máy phải là 1, 2 hoặc 3" >&2; exit 1;; esac; }

cmd_chuanbi() {
  [ -s "$SECRET_JSON" ] || { echo "Không thấy $SECRET_JSON"; exit 1; }
  for i in 1 2 3; do sshq "$(host $i)" true || { echo "VPS$i ($(host $i)): không đăng nhập được bằng khóa SSH"; exit 1; }; done
  echo "Đăng nhập 3 máy: OK"
  tmp=$(mktemp); sshq "$(host 1)" 'cat /root/work/count_lower.json' > "$tmp" || { echo "Không lấy được count_lower.json từ VPS1"; exit 1; }
  python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print("count_lower.json: {} Tòa, {} bản án".format(len(d), sum((v.get("total") or 0) for v in d.values())))' "$tmp" \
    || { echo "count_lower.json hỏng"; exit 1; }
  for i in 1 2 3; do
    h=$(host $i)
    sshq "$h" 'mkdir -p /root/work && umask 077 && cat > /root/work/client_secret.json' < "$SECRET_JSON"
    [ "$i" = 1 ] || sshq "$h" 'cat > /root/work/count_lower.json' < "$tmp"
  done
  rm -f "$tmp"
  echo "Đã chép file lên 3 máy. Đang cài đặt song song (5–10 phút; nhật ký ở $LOGD)..."
  pids=()
  for i in 1 2 3; do
    ( sshq "$(host $i)" "curl -fsSL $RAW/vps/dot2_setup.sh -o /root/dot2_setup.sh && bash /root/dot2_setup.sh" \
        > "$LOGD/setup_vps$i.log" 2>&1 ) & pids+=($!)
  done
  for i in 1 2 3; do
    wait "${pids[$((i - 1))]}"; rc=$?
    echo "--- VPS$i: $([ $rc = 0 ] && echo OK || echo "LỖI (mã $rc)") ---"; tail -4 "$LOGD/setup_vps$i.log"
  done
  echo; echo "Tiếp theo: bash ~/dot2_mac.sh capquyen 1   (rồi 2, rồi 3)"
}

cmd_capquyen() {
  h=$(host "$1")
  if lsof -nP -iTCP:53682 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Cổng 53682 trên MacBook đang bận (một phiên capquyen khác chưa thoát?). Đóng phiên đó rồi chạy lại."; exit 1
  fi
  ssh -t -o ServerAliveInterval=30 -L 53682:127.0.0.1:53682 "root@$h" "bash $R/vps/dot2_auth.sh"
}

cmd_chia() { sshq "$(host 1)" "$R/.venv/bin/python $R/vps/lower_courts.py /root/work/count_lower.json 3"; }

cmd_thu() { sshq "$(host 1)" "bash $R/vps/dot2_start.sh 1 --test"; }

cmd_chay() {
  for i in 1 2 3; do echo "=== VPS$i ==="; sshq "$(host $i)" "bash $R/vps/dot2_start.sh $i"; echo; done
}

cmd_tiendo() {
  for i in 1 2 3; do
    sshq "$(host $i)" "cd $R && TOAAN_WORK=/root/work .venv/bin/python vps/dot2_status.py --short" 2>/dev/null \
      || echo "VPS$i ($(host $i)): không đọc được tiến độ"
    echo
  done
}

cmd_theodoi() {
  every="${1:-30}"; tmp=$(mktemp -d)
  CM=(-o ControlMaster=auto -o ControlPath="$HOME/.ssh/cm-dot2-%h" -o ControlPersist=10m)
  trap 'rm -rf "$tmp"; tput cnorm 2>/dev/null; echo; exit 0' INT TERM
  tput civis 2>/dev/null
  while true; do
    for i in 1 2 3; do
      ( ssh -o BatchMode=yes -o ConnectTimeout=15 "${CM[@]}" "root@$(host $i)" \
          "cd $R && TOAAN_WORK=/root/work .venv/bin/python vps/dot2_watch.py" > "$tmp/$i.json" 2>/dev/null \
        || echo '{"err": 1}' > "$tmp/$i.json" ) &
    done
    wait
    cols=$(tput cols 2>/dev/null || echo 160)
    out=$(python3 - "$tmp" "$every" "$cols" <<'PY'
import json, os, shutil, sys
from datetime import datetime
d, every = sys.argv[1], sys.argv[2]
W = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 160
def f(n): return "{:,}".format(int(n)).replace(",", ".")
rows, recent, T = [], [], {}
keys = ["total", "listed", "got", "ok", "drive", "mac", "up_wait", "md_wait", "last_hour"]
meth = {}
L = []
L.append("THEO DÕI ĐỢT 2 — 3 VPS — {}   (làm mới {} giây/lần · Ctrl+C để thoát)".format(datetime.now().strftime("%d/%m/%Y %H:%M:%S"), every))
L.append("")
hdr = "{:<6}{:>11}{:>10}{:>12}{:>12}{:>15}{:>11}{:>11}{:>9}{:>9}{:>9}  {}".format(
    "Máy", "Trên cổng", "Lấy DS", "PDF về VPS", "Đặt tên+MD", "PDF lên Drive", "MD về Mac", "Chờ Drive", "Chờ Mac", "Bản/giờ", "Ổ trống", "Đang tải")
L.append(hdr); L.append("-" * min(W, len(hdr) + 18))
for i in (1, 2, 3):
    try:
        j = json.load(open(os.path.join(d, "%d.json" % i)))
    except Exception:
        j = {"err": 1}
    if j.get("err"):
        L.append("VPS%d  — không kết nối được" % i); continue
    j["drive"] = max(j["ok"] - j["up_wait"], 0)
    j["mac"] = max(j["ok"] - j["md_wait"], 0)
    for k in keys: T[k] = T.get(k, 0) + j[k]
    for m, n in j["methods"].items(): meth[m] = meth.get(m, 0) + n
    st = "XONG" if j["done"] else (j["cur"] or "-")
    sv = "".join("●" if v == "active" else "○" for v in j["svc"].values())
    L.append("{:<6}{:>11}{:>10}{:>12}{:>12}{:>15}{:>11}{:>11}{:>9}{:>9}{:>8}G  {} {}".format(
        "VPS%d" % i, f(j["total"]), f(j["listed"]), f(j["got"]), f(j["ok"]), f(j["drive"]), f(j["mac"]),
        f(j["up_wait"]), f(j["md_wait"]), f(j["last_hour"]), j["free_gb"], sv, st))
    for r in j["recent"]: r["vps"] = i; recent.append(r)
if T:
    L.append("-" * min(W, len(hdr) + 18))
    L.append("{:<6}{:>11}{:>10}{:>12}{:>12}{:>15}{:>11}{:>11}{:>9}{:>9}".format(
        "TỔNG", f(T["total"]), f(T["listed"]), f(T["got"]), f(T["ok"]), f(T["drive"]), f(T["mac"]),
        f(T["up_wait"]), f(T["md_wait"]), f(T["last_hour"])))
    pct = T["ok"] * 100.0 / max(T["total"], 1)
    rate = T["last_hour"]
    eta = "~%.0f giờ" % ((T["total"] - T["ok"]) / rate) if rate else "chưa tính được"
    L.append("")
    L.append("Tiến độ: {:.1f}% · tốc độ 3 máy (60 phút qua): {} bản/giờ · còn lại {} bản, {}".format(
        pct, f(rate), f(max(T["total"] - T["ok"], 0)), eta))
    L.append("Lớp chữ: " + " · ".join("{} {}".format(m, f(n)) for m, n in sorted(meth.items())))
    L.append("Dịch vụ ●●● = tải · đặt tên+MD · đẩy Drive (○ = đang tắt).  'MD về Mac' chỉ tăng khi lệnh keo đang chạy.")
L.append("")
L.append("20 FILE GẦN NHẤT (Drive/Mac: ✓ đã tới, … đang chờ)")
recent.sort(key=lambda r: r["t"], reverse=True)
for r in recent[:20]:
    tag = "{} VPS{} {:<15} Drive{} Mac{} ".format(r["t"][11:19], r["vps"], r["m"] if r["s"] != "LOI" else "LỖI",
                                                 "✓" if r["drive"] else "…", "✓" if r["mac"] else "…")
    name = r["n"]
    room = max(W - len(tag) - 1, 20)
    L.append(tag + (name if len(name) <= room else name[:room - 1] + "…"))
print("\n".join(L))
PY
)
    clear; printf '%s\n' "$out"
    sleep "$every"
  done
}

cmd_suaten() {
  [ -d "$MD_ROOT" ] || { echo "Không thấy thư mục: $MD_ROOT"; exit 1; }
  for i in 1 2 3; do
    h=$(host $i); echo "=== VPS$i ==="
    sshq "$h" "/usr/local/bin/toaan-update; systemctl stop toaan-process2 toaan-upload3; \
      cd $R && TOAAN_WORK=/root/work .venv/bin/python vps/fix_names2.py" || { echo "VPS$i: LỖI đổi tên"; continue; }
    sshq "$h" 'f=/root/work/state/rename_mac.tsv; [ -s $f ] && cat $f' > "$LOGD/rename_mac_vps$i.tsv"
    if [ -s "$LOGD/rename_mac_vps$i.tsv" ]; then
      python3 - "$MD_ROOT" "$LOGD/rename_mac_vps$i.tsv" <<'PY'
import json, os, re, sys
root, tsv = sys.argv[1], sys.argv[2]
rows = [l.rstrip("\n").split("\t") for l in open(tsv, encoding="utf-8") if l.strip()]
todo = []
for old, new, loai, pdf, so, sn in rows:
    po, pn = os.path.join(root, old), os.path.join(root, new)
    if os.path.exists(po):
        t = open(po, encoding="utf-8").read()
        t = re.sub(r'^pdf: ".*"$', "pdf: " + json.dumps(pdf, ensure_ascii=False), t, count=1, flags=re.M)
        t = re.sub(r'^loai_vu_viec: ".*"$', "loai_vu_viec: " + json.dumps(loai, ensure_ascii=False), t, count=1, flags=re.M)
        todo.append((po, pn, t.replace("\n# %s\n" % so, "\n# %s\n" % sn, 1)))
for po, _, _ in todo:
    os.remove(po)
for _, pn, t in todo:
    os.makedirs(os.path.dirname(pn), exist_ok=True)
    open(pn, "w", encoding="utf-8").write(t)
print("Mac: đổi tên %d MD (danh sách %d dòng)" % (len(todo), len(rows)))
PY
      [ $? = 0 ] && sshq "$h" 'mv /root/work/state/rename_mac.tsv /root/work/state/rename_mac.done.$(date +%s)'
    fi
    sshq "$h" "systemctl start toaan-process2 toaan-upload3; echo \"VPS$i: đã bật lại đặt tên + đẩy Drive\""
  done
}

cmd_dung() {
  for i in 1 2 3; do sshq "$(host $i)" 'systemctl stop toaan-lower; echo "VPS'"$i"': đã dừng tải (toaan-lower)"'; done
}

cmd_keo() {
  [ -d "$MD_ROOT" ] || { echo "Không thấy thư mục: $MD_ROOT"; exit 1; }
  echo "$(date '+%F %T') Kéo MD đợt 2 từ 3 VPS về: $MD_ROOT"
  total=0
  while true; do
    free_gb=$(df -g "$HOME" | awk 'NR==2{print $4}')
    if [ "${free_gb:-0}" -lt 15 ]; then
      echo "$(date '+%F %T') MacBook còn ${free_gb} GB trống — chờ 10 phút"; sleep 600; continue
    fi
    got_any=0; done_all=1
    for i in 1 2 3; do
      h=$(host $i)
      batches=$(sshq "$h" "bash $R/vps/outbox_md2.sh" 2>/dev/null) || { done_all=0; continue; }
      while read -r b n; do
        [ -z "$b" ] && continue
        got=$(sshq "$h" "tar -C /root/work/outbox_md/$b -cf - ." | tar -C "$MD_ROOT" -xvf - 2>&1 | grep '^x ' | grep -vc '/$')
        if [ "$got" -ge "$n" ]; then
          sshq "$h" "rm -rf /root/work/outbox_md/$b"; total=$((total + n)); got_any=1
          echo "$(date '+%F %T') VPS$i lô $b: $n MD (tổng $total)"
        else
          echo "$(date '+%F %T') VPS$i lô $b: chỉ nhận $got/$n — sẽ kéo lại"; done_all=0
        fi
      done <<< "$batches"
      [ -n "$batches" ] && done_all=0
      sshq "$h" 'test -f /root/work/DOT2_ALL_DONE && [ -z "$(find /root/work/md2 -name "*.md" -print -quit)" ]' || done_all=0
    done
    [ "$done_all" = 1 ] && { echo "$(date '+%F %T') Cả 3 máy đã xong. Tổng $total MD."; exit 0; }
    [ "$got_any" = 0 ] && { echo "$(date '+%F %T') Chưa có MD mới (tổng $total). Chờ 5 phút."; sleep 300; }
  done
}

case "${1:-}" in
  chuanbi) cmd_chuanbi;;
  capquyen) cmd_capquyen "${2:-}";;
  chia) cmd_chia;;
  thu) cmd_thu;;
  chay) cmd_chay;;
  tiendo) cmd_tiendo;;
  theodoi) cmd_theodoi "${2:-30}";;
  keo) cmd_keo;;
  suaten) cmd_suaten;;
  dung) cmd_dung;;
  *) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//';;
esac
