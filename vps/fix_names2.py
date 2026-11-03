#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Đổi lại tên các bản án đợt 2 đã xử lý theo cách đặt tên mới của process2.py (04/11/2026):
  - số ngắn: '93/2017/HSST' → '93' (trước: '932017HSST');
  - loại vụ việc suy từ ký hiệu trong số / quan hệ pháp luật khi cổng không ghi (trước: rơi vào 09 KHAC).
Với mỗi dòng processed2.csv có tên/thư mục đổi:
  PDF còn trên VPS (upload2) → đổi tên tại chỗ; đã lên Drive → rclone moveto trên Drive.
  MD còn trên VPS (md2, outbox_md) → sửa YAML + tiêu đề, chuyển sang tên mới trong md2;
  MD đã về MacBook → ghi state/rename_mac.tsv để tools/dot2_mac.sh suaten đổi trên Mac.
Dòng LOI mà PDF còn trong data2 → xóa khỏi state để process2 xử lý lại.
Phải dừng toaan-process2 và toaan-upload3 trong lúc chạy (dot2_mac.sh suaten tự làm).
  --dry-run  chỉ in thống kê
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import process2 as X  # noqa: E402

WORK = X.WORK


def load_records():
    out = {}
    for rf in X.DATA2.glob("*/*/*/records_full.jsonl"):
        cj = rf.parent / "court.json"
        if not cj.exists():
            continue
        court = json.loads(cj.read_text(encoding="utf-8"))
        with rf.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("id"):
                    out[r["id"]] = (court, r)
    return out


def fix_md_text(txt, old, new, rel_new, ct):
    pdf = str(Path(X.PDF_LABEL) / rel_new / f"{new}.pdf")
    txt = re.sub(r'^pdf: ".*"$', "pdf: " + json.dumps(pdf, ensure_ascii=False), txt, count=1, flags=re.M)
    txt = re.sub(r'^loai_vu_viec: ".*"$', "loai_vu_viec: " + json.dumps(X.CASE_LABEL.get(ct, ct), ensure_ascii=False),
                 txt, count=1, flags=re.M)
    return txt.replace(f"\n# {old}\n", f"\n# {new}\n", 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    st = X.STATE_CSV
    if not st.exists():
        print("Chưa có processed2.csv")
        return
    with st.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    recs = load_records()
    used, changes, keep, retry = set(), [], [], 0
    for r in rows:
        if r["status"] == "LOI":
            cr = recs.get(r["id"])
            if cr and cr[1].get("pdf_path") and Path(cr[1]["pdf_path"]).exists():
                retry += 1
                continue  # bỏ dòng: process2 làm lại
            keep.append(r)
            continue
        cr = recs.get(r["id"])
        if not cr:
            keep.append(r)
            used.add((r["dest_dir"], r["final_stem"]))
            continue
        rel, stem, ct, _ = X.target(*cr)
        final, n = stem, 2
        while (str(rel), final) in used:
            final = f"{stem} (bản {n})"
            n += 1
        used.add((str(rel), final))
        if (str(rel), final) != (r["dest_dir"], r["final_stem"]):
            changes.append((r, str(rel), final, ct, len(keep)))
            r = dict(r, dest_dir=str(rel), final_stem=final, case_type=ct)
        keep.append(r)
    print(f"Tổng {len(rows)} dòng | cần đổi tên {len(changes)} | dòng lỗi xử lý lại {retry}")
    for r, rel, final, _, _ in changes[:8]:
        print(f"  {r['final_stem']}\n   → {final}  [{rel}]")
    if a.dry_run or (not changes and not retry):
        return

    # Tên mới của file này có thể đang là tên cũ của file khác → đổi 2 bước qua tên tạm để không ghi đè
    olds = {(c[0]["dest_dir"], c[0]["final_stem"]) for c in changes}
    cur = {i: (c[0]["dest_dir"], c[0]["final_stem"]) for i, c in enumerate(changes)}

    def mv(src, dst):
        o = WORK / "upload2" / src[0] / f"{src[1]}.pdf"
        if o.exists():
            n_ = WORK / "upload2" / dst[0] / f"{dst[1]}.pdf"
            n_.parent.mkdir(parents=True, exist_ok=True)
            o.rename(n_)
            return "vps"
        rc = subprocess.run(["rclone", "moveto", f"banan:{src[0]}/{src[1]}.pdf", f"banan:{dst[0]}/{dst[1]}.pdf",
                             "--log-level", "ERROR"]).returncode
        return "drive" if rc == 0 else "loi"

    res = ["?"] * len(changes)

    def phase1(i):
        c = changes[i]
        tmp = (c[0]["dest_dir"], f"{c[0]['final_stem']} __doiten{c[0]['id']}")
        h = mv(cur[i], tmp)
        if h != "loi":
            cur[i] = tmp
        else:
            res[i] = "loi"

    def phase2(i):
        if res[i] == "loi":
            return
        c = changes[i]
        res[i] = mv(cur[i], (c[1], c[2]))

    conflict = [i for i, c in enumerate(changes) if (c[1], c[2]) in olds]
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(phase1, [i for i in range(len(changes))
                             if (changes[i][0]["dest_dir"], changes[i][0]["final_stem"]) in {(changes[j][1], changes[j][2]) for j in conflict}]))
        list(ex.map(phase2, range(len(changes))))
    # MD trên VPS: đọc hết trước, xóa hết bản cũ, rồi mới ghi bản mới (không ghi đè lẫn nhau)
    mac_lines, md_new, md_old = [], [], []
    for i, ((r, rel, final, ct, idx), how) in enumerate(zip(changes, res)):
        if how == "loi":  # không đổi được: giữ đúng vị trí hiện tại của PDF
            keep[idx] = dict(r, dest_dir=cur[i][0], final_stem=cur[i][1])
            continue
        cands = [WORK / "md2" / r["dest_dir"] / f"{r['final_stem']}.md"] + \
            list((WORK / "outbox_md").glob(f"*/{r['dest_dir']}/{r['final_stem']}.md"))
        src = next((p for p in cands if p.exists()), None)
        if src:
            md_old.append(src)
            md_new.append((WORK / "md2" / rel / f"{final}.md",
                           fix_md_text(src.read_text(encoding="utf-8"), r["final_stem"], final, rel, ct)))
        else:
            pdf = str(Path(X.PDF_LABEL) / rel / f"{final}.pdf")
            mac_lines.append("\t".join([f"{r['dest_dir']}/{r['final_stem']}.md", f"{rel}/{final}.md",
                                        X.CASE_LABEL.get(ct, ct), pdf, r["final_stem"], final]))
    for p in md_old:
        p.unlink()
    for dst, txt in md_new:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(txt, encoding="utf-8")
    md_vps = len(md_new)
    if mac_lines:
        with (WORK / "state" / "rename_mac.tsv").open("a", encoding="utf-8") as f:
            f.write("".join(x + "\n" for x in mac_lines))
    tmp = st.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=X.FIELDNAMES)
        w.writeheader()
        w.writerows(keep)
    tmp.replace(st)
    print(f"PDF: đổi trên VPS {res.count('vps')}, trên Drive {res.count('drive')}, lỗi {res.count('loi')} | "
          f"MD: sửa trên VPS {md_vps}, chờ Mac đổi {len(mac_lines)}")


if __name__ == "__main__":
    main()
