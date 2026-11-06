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
#   bash ~/dot2_mac.sh dem [1|2|3]    đếm số bản án toàn quốc (Tòa cấp tỉnh/huyện/khu vực còn lại), chia 3 máy
#   bash ~/dot2_mac.sh ketquadem      xem tiến độ / kết quả đếm, ước tính dung lượng và thời gian tải
#   bash ~/dot2_mac.sh dung           dừng tải trên cả 3 máy (khẩn cấp)
#   bash ~/dot2_mac.sh ocr dem        đếm số bản / trang ảnh NATIVE_MOT_PHAN còn phải OCR trên 3 máy
#   bash ~/dot2_mac.sh ocr thu        OCR thử 40 bản trên mỗi máy, đo tốc độ, ước tính thời gian
#   bash ~/dot2_mac.sh ocr chay       chạy OCR trên 3 máy (nền, ưu tiên thấp; tự dừng khi xong)
#   bash ~/dot2_mac.sh ocr tiendo     xem tiến độ OCR
#   caffeinate -is bash ~/dot2_mac.sh ghepocr   kéo chữ OCR về và ghép vào MD trong MDBANAN
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
  # Không dùng kết nối ssh dùng chung (ControlMaster): sau khi Mac ngủ/đổi mạng nó treo cả màn hình
  CM=(-o ServerAliveInterval=10 -o ServerAliveCountMax=2)
  rm -f "$HOME"/.ssh/cm-dot2-* 2>/dev/null
  trap 'rm -rf "$tmp"; tput cnorm 2>/dev/null; echo; exit 0' INT TERM
  tput civis 2>/dev/null
  while true; do
    pids=()
    for i in 1 2 3; do
      rm -f "$tmp/$i.json"
      ( ssh -o BatchMode=yes -o ConnectTimeout=15 "${CM[@]}" "root@$(host $i)" \
          "cd $R && TOAAN_WORK=/root/work .venv/bin/python vps/dot2_watch.py" > "$tmp/$i.part" 2>/dev/null \
          && mv "$tmp/$i.part" "$tmp/$i.json" || echo '{"err": 1}' > "$tmp/$i.json" ) & pids+=($!)
    done
    ( sleep 60; kill "${pids[@]}" 2>/dev/null ) & dog=$!   # một máy treo không làm đứng cả màn hình
    wait "${pids[@]}" 2>/dev/null; kill $dog 2>/dev/null
    for i in 1 2 3; do [ -s "$tmp/$i.json" ] || echo '{"err": 1}' > "$tmp/$i.json"; done
    cols=$(stty size </dev/tty 2>/dev/null | awk '{print $2}'); [ -n "$cols" ] || cols=160
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
    # Tốc độ đo trên MacBook: so sánh số liệu với lần đo cách đây tối đa 30 phút (lưu trong thư mục tạm)
    import time as _t
    hp = os.path.join(d, "hist.json")
    try:
        hist = json.load(open(hp))
    except Exception:
        hist = []
    now = _t.time()
    hist = [h for h in hist if now - h[0] <= 1800] + [[now, T["got"], T["drive"], T["ok"]]]
    json.dump(hist, open(hp, "w"))
    h0 = hist[0]
    span = (now - h0[0]) / 3600.0
    L.append("")
    if span >= 0.05:
        r_got, r_drv = (T["got"] - h0[1]) / span, (T["drive"] - h0[2]) / span
        left = max(T["total"] - T["got"], 0)
        eta = "~%.0f giờ" % (left / r_got) if r_got > 0 else "chưa tính được"
        L.append("Tiến độ: {:.1f}% · đo {:.0f} phút gần nhất: tải về VPS {} PDF/giờ, lên Drive {} PDF/giờ · còn {} bản, {}".format(
            pct, span * 60, f(r_got), f(r_drv), f(left), eta))
    else:
        L.append("Tiến độ: {:.1f}% · đang đo tốc độ (cần vài phút sau khi mở màn hình)".format(pct))
    L.append("Lớp chữ: " + " · ".join("{} {}".format(m, f(n)) for m, n in sorted(meth.items())))
    L.append("Dịch vụ ●●● = tải · đặt tên+MD · đẩy Drive (○ = đang tắt).  'MD về Mac' chỉ tăng khi lệnh keo đang chạy.")
L.append("")
L.append("20 FILE GẦN NHẤT (Drive/Mac: ✓ đã tới, … đang chờ)")
recent.sort(key=lambda r: r["t"], reverse=True)
for r in recent[:20]:
    tag = "{} VPS{} {:<15} Drive{} Mac{} ".format(r["t"][11:19], r["vps"], r["m"] if r["s"] != "LOI" else "LỖI",
                                                 "✓" if r["drive"] else "…", "✓" if r["mac"] else "…")
    name = r["n"]
    room = max(W - len(tag) - 1, 30)
    # Tên dài hơn bề ngang cửa sổ: xuống dòng, thụt vào thẳng cột tên (không cắt)
    import textwrap
    parts = textwrap.wrap(name, room, break_long_words=True) or [name]
    L.append(tag + parts[0])
    for part in parts[1:]:
        L.append(" " * len(tag) + part)
print("\n".join(L))
PY
)
    clear; printf '%s\n' "$out"
    sleep "$every"
  done
}

cmd_suaten() {
  [ -d "$MD_ROOT" ] || { echo "Không thấy thư mục: $MD_ROOT"; exit 1; }
  if ! mkdir "$LOGD/suaten.lock" 2>/dev/null; then
    echo "Đang có một lượt suaten khác chạy (cửa sổ khác). Chờ lượt đó xong rồi chạy lại."
    echo "(Nếu chắc chắn không còn lượt nào: rmdir \"$LOGD/suaten.lock\")"; exit 1
  fi
  trap 'rmdir "$LOGD/suaten.lock" 2>/dev/null' EXIT
  for i in 1 2 3; do
    h=$(host $i); echo "=== VPS$i ==="
    sshq "$h" "/usr/local/bin/toaan-update; systemctl stop toaan-process2 toaan-upload3; \
      cd $R && TOAAN_WORK=/root/work .venv/bin/python vps/fix_names2.py" || { echo "VPS$i: LỖI đổi tên"; continue; }
    sshq "$h" 'f=/root/work/state/rename_mac.tsv; [ -s $f ] && cat $f' > "$LOGD/rename_mac_vps$i.tsv"
    if [ -s "$LOGD/rename_mac_vps$i.tsv" ] || [ -s "$LOGD/rename_pending_vps$i.tsv" ]; then
      python3 - "$MD_ROOT" "$LOGD/rename_mac_vps$i.tsv" "$LOGD/rename_pending_vps$i.tsv" <<'PY'
import json, os, re, sys
root, tsv, pend = sys.argv[1], sys.argv[2], sys.argv[3]
lines = []
for fn in (pend, tsv):  # dòng còn treo từ lần trước + danh sách mới
    if os.path.exists(fn):
        lines += [l.rstrip("\n").split("\t") for l in open(fn, encoding="utf-8") if l.strip()]
# Gộp chuỗi đổi tên A→B, B→C thành A→C (nhiều lượt suaten nối tiếp nhau)
final, rev = {}, {}
for old, new, loai, pdf, so, sn in lines:
    origin = rev.pop(old, old)
    head = final[origin][4] if origin in final else so
    final[origin] = (new, loai, pdf, sn, head)
    rev[new] = origin
todo, pending, missing = [], [], 0
for origin, (new, loai, pdf, sn, head) in final.items():
    po, pn = os.path.join(root, origin), os.path.join(root, new)
    if origin == new:
        continue
    try:
        t = open(po, encoding="utf-8").read()
    except FileNotFoundError:
        if not os.path.exists(pn):
            missing += 1
        continue
    except OSError:
        pending.append("\t".join([origin, new, loai, pdf, head, sn])); continue
    t = re.sub(r'^pdf: ".*"$', "pdf: " + json.dumps(pdf, ensure_ascii=False), t, count=1, flags=re.M)
    t = re.sub(r'^loai_vu_viec: ".*"$', "loai_vu_viec: " + json.dumps(loai, ensure_ascii=False), t, count=1, flags=re.M)
    todo.append((po, pn, t.replace("\n# %s\n" % head, "\n# %s\n" % sn, 1), "\t".join([origin, new, loai, pdf, head, sn])))
done = 0
for po, _, _, line in todo:  # xóa hết bản cũ trước rồi mới ghi bản mới: không ghi đè lẫn nhau
    try:
        os.remove(po)
    except OSError:
        pass
for po, pn, t, line in todo:
    try:
        os.makedirs(os.path.dirname(pn), exist_ok=True)
        open(pn, "w", encoding="utf-8").write(t)
        done += 1
    except OSError:
        pending.append(line)
open(pend, "w", encoding="utf-8").write("".join(x + "\n" for x in pending))
print("Mac: đổi tên %d MD | chưa có trên Mac %d | để lần sau %d" % (done, missing, len(pending)))
PY
      [ $? = 0 ] && sshq "$h" 'mv /root/work/state/rename_mac.tsv /root/work/state/rename_mac.done.$(date +%s)' \
        && rm -f "$LOGD/rename_mac_vps$i.tsv"
    fi
    sshq "$h" "systemctl start toaan-process2 toaan-upload3; echo \"VPS$i: đã bật lại đặt tên + đẩy Drive\""
  done
}

cmd_dem() {
  only="${1:-}"
  tmp=$(mktemp)
  sshq "$(host 1)" 'cat /root/work/probe_levels.json' > "$tmp" || { echo "Không lấy được probe_levels.json từ VPS1"; exit 1; }
  for i in 1 2 3; do
    [ -n "$only" ] && [ "$only" != "$i" ] && continue
    h=$(host $i)
    if ! sshq "$h" 'test -f /root/work/DOWNLOAD2_DONE' && [ "${NGAY:-0}" != "1" ]; then
      echo "VPS$i: đợt 2 chưa tải xong — chưa đếm (chạy lại sau, hoặc NGAY=1 bash ~/dot2_mac.sh dem $i để đếm luôn)"; continue
    fi
    [ "$i" = 1 ] || sshq "$h" 'cat > /root/work/probe_levels.json' < "$tmp"
    sshq "$h" "/usr/local/bin/toaan-update >/dev/null 2>&1; systemctl is-active -q toaan-count-all && echo 'VPS$i: đang đếm rồi' || \
      { systemd-run --unit toaan-count-all --collect --setenv=TOAAN_WORK=/root/work \
          $R/.venv/bin/python $R/tools/count_all.py --shard $i/3 >/dev/null && echo 'VPS$i: đã bắt đầu đếm'; }"
  done
  rm -f "$tmp"
  echo "Xem tiến độ: bash ~/dot2_mac.sh ketquadem"
}

cmd_ketquadem() {
  d=$(mktemp -d)
  for i in 1 2 3; do
    sshq "$(host $i)" "cat /root/work/count_all_$i.json 2>/dev/null; true" > "$d/$i.json"
    st=$(sshq "$(host $i)" 'systemctl is-active toaan-count-all 2>/dev/null; true')
    echo "VPS$i: ${st:-?}"
  done
  python3 - "$d" "$LOGD/dem_toan_quoc.csv" <<'PY'
import csv, json, os, sys
d, out = sys.argv[1], sys.argv[2]
rows = []
for i in (1, 2, 3):
    p = os.path.join(d, "%d.json" % i)
    try:
        rows += list(json.load(open(p)).values())
    except Exception:
        pass
def f(n): return "{:,}".format(int(n)).replace(",", ".")
ok = [r for r in rows if isinstance(r.get("total"), int)]
bad = [r for r in rows if not isinstance(r.get("total"), int)]
tot = sum(r["total"] for r in ok)
by = {}
for r in ok:
    k = (r["parent"], r["kind"])
    by[k] = by.get(k, 0) + r["total"]
prov = {}
for (p, kind), n in by.items():
    prov.setdefault(p, {"tinh": 0, "huyen": 0, "khu-vuc": 0})[kind] += n
print("\nĐã đếm %d Tòa (%d không đọc được số: 0 bản án hoặc lỗi). Tổng: %s bản án" % (len(rows), len(bad), f(tot)))
for kind, lab in (("tinh", "cấp tỉnh"), ("huyen", "cấp huyện (cũ)"), ("khu-vuc", "khu vực")):
    print("  %-16s %s" % (lab, f(sum(r["total"] for r in ok if r["kind"] == kind))))
print("\nƯớc tính nếu tải hết: PDF ~%.2f TB (1,5 MB/bản) · MD ~%.0f GB (25 KB/bản; ~30 KB sau OCR)" % (tot * 1.5 / 1e6, tot * 25 / 1e6))
for n, rate in ((3, 6900), (4, 8800), (5, 10000), (6, 10500)):
    print("  %d VPS (~%s bản/giờ): ~%.0f giờ ≈ %.1f ngày" % (n, f(rate), tot / rate, tot / rate / 24))
print("\nTheo tỉnh/thành (20 lớn nhất):")
for p, v in sorted(prov.items(), key=lambda x: -sum(x[1].values()))[:20]:
    print("  %-40s %9s  (tỉnh %s · huyện %s · khu vực %s)" % (p[:40], f(sum(v.values())), f(v["tinh"]), f(v["huyen"]), f(v["khu-vuc"])))
with open(out, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["cap", "ma_toa", "ten_toa", "tinh_thanh", "loai", "so_ban_an", "ghi_chu"])
    for r in sorted(rows, key=lambda r: (r["parent"], r["level"], r["name"])):
        w.writerow([r["level"], r["value"], r["name"], r["parent"], r["kind"], r.get("total"), r.get("note", "")])
print("\nBảng đầy đủ từng Tòa: " + out)
PY
  rm -rf "$d"
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
    if [ "${free_gb:-0}" -lt "${MIN_FREE_GB:-15}" ]; then
      echo "$(date '+%F %T') MacBook còn ${free_gb} GB trống (ngưỡng ${MIN_FREE_GB:-15} GB) — chờ 10 phút"; sleep 600; continue
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

cmd_ocr() {
  sub="${1:-dem}"
  for i in 1 2 3; do
    h=$(host $i)
    case "$sub" in
      dem|thu|chay)
        sshq "$h" "/usr/local/bin/toaan-update >/dev/null 2>&1; command -v tesseract >/dev/null && tesseract --list-langs 2>/dev/null | grep -qx vie || \
          DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tesseract-ocr tesseract-ocr-vie >/dev/null 2>&1" ;;
    esac
    case "$sub" in
      dem) echo "VPS$i: $(sshq "$h" "TOAAN_WORK=/root/work $R/.venv/bin/python $R/vps/ocr2.py --dem")";;
      thu) ( out=$(sshq "$h" "systemctl is-active -q toaan-ocr2 && echo 'đang chạy OCR chính thức — bỏ qua thử' || \
               TOAAN_WORK=/root/work nice -n 10 $R/.venv/bin/python $R/vps/ocr2.py --thu 40 | tail -2")
             printf '=== VPS%s ===\n%s\n' "$i" "$out" ) & ;;
      chay) sshq "$h" "systemctl is-active -q toaan-ocr2 && echo 'VPS$i: đang chạy OCR rồi' || \
             { systemd-run --unit toaan-ocr2 --collect --nice=10 --setenv=TOAAN_WORK=/root/work \
                 $R/.venv/bin/python $R/vps/ocr2.py --loop >/dev/null && echo 'VPS$i: đã bắt đầu OCR'; }";;
      tiendo) echo "--- VPS$i: $(sshq "$h" 'systemctl is-active toaan-ocr2 2>/dev/null; test -f /root/work/OCR2_DONE && echo XONG; true' | tr '\n' ' ')"
              sshq "$h" "TOAAN_WORK=/root/work $R/.venv/bin/python $R/vps/ocr2.py --dem; \
                echo \"lô chờ Mac kéo: \$(ls /root/work/outbox_ocr 2>/dev/null | grep -c '^ocr-')\"; tail -1 /root/work/logs/ocr2.log 2>/dev/null; true";;
      *) echo "Lệnh: ocr dem | thu | chay | tiendo"; exit 1;;
    esac
  done
  wait
  [ "$sub" = chay ] && echo "Tiếp theo (cửa sổ Terminal riêng): caffeinate -is bash ~/dot2_mac.sh ghepocr"
  true
}

cmd_ghepocr() {
  [ -d "$MD_ROOT" ] || { echo "Không thấy thư mục: $MD_ROOT"; exit 1; }
  IN="$LOGD/ocr_in"; mkdir -p "$IN"
  curl -fsSL "$RAW/tools/ocr_ghep.py" -o "$LOGD/ocr_ghep.py" || { echo "Không tải được ocr_ghep.py"; exit 1; }
  echo "$(date '+%F %T') Kéo chữ OCR từ 3 VPS và ghép vào MD: $MD_ROOT"
  while true; do
    if [ -d "$LOGD/suaten.lock" ]; then echo "$(date '+%F %T') suaten đang chạy — chờ 2 phút"; sleep 120; continue; fi
    got_any=0; done_all=1
    for i in 1 2 3; do
      h=$(host $i)
      batches=$(sshq "$h" 'cd /root/work/outbox_ocr 2>/dev/null && for d in ocr-*/; do [ -d "$d" ] && echo "${d%/} $(ls "$d" | wc -l)"; done; true') \
        || { done_all=0; continue; }
      while read -r b n; do
        [ -z "$b" ] && continue
        mkdir -p "$IN/$b"
        sshq "$h" "tar -C /root/work/outbox_ocr/$b -cf - ." | tar -C "$IN/$b" -xf - 2>/dev/null
        got=$(find "$IN/$b" -name '*.json' | wc -l | tr -d ' ')
        if [ "$got" -ge "$n" ]; then
          sshq "$h" "rm -rf /root/work/outbox_ocr/$b"; got_any=1
          echo "$(date '+%F %T') VPS$i lô $b: $n bản"
        else
          echo "$(date '+%F %T') VPS$i lô $b: chỉ nhận $got/$n — sẽ kéo lại"; done_all=0
        fi
      done <<< "$batches"
      [ -n "$batches" ] && done_all=0
      sshq "$h" 'test -f /root/work/OCR2_DONE' || done_all=0
    done
    python3 "$LOGD/ocr_ghep.py" "$IN" "$MD_ROOT" "$LOGD/ma_cong_index.tsv"
    [ "$done_all" = 1 ] && { echo "$(date '+%F %T') OCR cả 3 máy đã xong và đã ghép."; exit 0; }
    [ "$got_any" = 0 ] && { echo "$(date '+%F %T') Chưa có lô OCR mới. Chờ 5 phút."; sleep 300; }
  done
}

case "${1:-}" in
  ocr) cmd_ocr "${2:-dem}";;
  ghepocr) cmd_ghepocr;;
  chuanbi) cmd_chuanbi;;
  capquyen) cmd_capquyen "${2:-}";;
  chia) cmd_chia;;
  thu) cmd_thu;;
  chay) cmd_chay;;
  tiendo) cmd_tiendo;;
  theodoi) cmd_theodoi "${2:-30}";;
  keo) cmd_keo;;
  suaten) cmd_suaten;;
  dem) cmd_dem "${2:-}";;
  ketquadem) cmd_ketquadem;;
  dung) cmd_dung;;
  *) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//';;
esac
