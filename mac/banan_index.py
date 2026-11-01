#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chỉ mục bản án MDBANAN (SQLite) — tra cứu nhanh theo Thẩm phán, Tòa, ngày, loại vụ việc, quan hệ pháp luật.

Đọc khối thông tin đầu mỗi file MD trong MDBANAN, ghi vào MDBANAN/_INDEX/banan.db.
Cập nhật tăng dần: chỉ đọc lại file mới hoặc đã sửa. Tìm không phân biệt dấu, khớp một phần.

  python3 banan_index.py capnhat
  python3 banan_index.py tim --tham-phan "phan thi lien" --tu 2023 --loai "dan su"
  python3 banan_index.py tim --toa KV3 --qhpl "hop dong vay" --xuat ketqua.csv
  python3 banan_index.py thongke --tham-phan "phan thi lien"
  python3 banan_index.py nguoi --toa "quan 1" --vai-tro tham_phan
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(os.environ.get("MDBANAN", Path.home() / "My Drive" / "000 - OBSIDIAN" / "MDBANAN"))
FIELDS = ["toa", "cap", "loai_vu_viec", "so", "ngay", "loai_van_ban", "cap_xet_xu", "quan_he_phap_luat",
          "ocr_mot_phan", "kiem_tra_ten", "ma_cong", "nguon", "pdf", "trich_xuat"]
ROLES = ["tham_phan", "thu_ky", "kiem_sat_vien"]


def kd(s):
    """Bỏ dấu, chữ thường, gộp khoảng trắng."""
    s = unicodedata.normalize("NFD", str(s or "").replace("đ", "d").replace("Đ", "D"))
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).lower().strip()


def vn(n):
    return f"{n:,}".replace(",", ".")


def db_path(root):
    return Path(root) / "_INDEX" / "banan.db"


def connect(root):
    p = db_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS banan(
      path TEXT PRIMARY KEY, mtime REAL, ma_noi TEXT, nhom TEXT, cap_toa TEXT, loai_thu_muc TEXT,
      toa TEXT, cap TEXT, loai_vu_viec TEXT, so TEXT, ngay TEXT, nam INTEGER, loai_van_ban TEXT,
      cap_xet_xu TEXT, quan_he_phap_luat TEXT, ocr_mot_phan INTEGER, kiem_tra_ten INTEGER, ma_cong TEXT,
      nguon TEXT, pdf TEXT, trich_xuat TEXT, tham_phan TEXT, thu_ky TEXT, kiem_sat_vien TEXT, tim TEXT, gd TEXT);
    CREATE TABLE IF NOT EXISTS nguoi(path TEXT, vai_tro TEXT, ten TEXT, ten_kd TEXT);
    CREATE INDEX IF NOT EXISTS i_nguoi ON nguoi(ten_kd, vai_tro);
    CREATE INDEX IF NOT EXISTS i_nguoi_path ON nguoi(path);
    CREATE INDEX IF NOT EXISTS i_ngay ON banan(ngay);
    CREATE INDEX IF NOT EXISTS i_ma_cong ON banan(ma_cong);
    """)
    return con


def read_frontmatter(path):
    fm = {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        if f.readline().strip() != "---":
            return None
        for _ in range(80):
            line = f.readline()
            if not line or line.strip() == "---":
                break
            k, _, v = line.partition(":")
            try:
                fm[k.strip()] = json.loads(v.strip())
            except json.JSONDecodeError:
                fm[k.strip()] = v.strip().strip('"')
    return fm


def capnhat(root, quiet=False):
    t0 = time.time()
    root = Path(root)
    con = connect(root)
    known = dict(con.execute("SELECT path, mtime FROM banan"))
    seen, n_new = set(), 0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith(("_INDEX", "."))]
        for fn in fns:
            if not fn.endswith(".md") or fn.startswith((".", "_")):
                continue
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, root)
            seen.add(rel)
            mt = os.path.getmtime(full)
            if known.get(rel) == mt:
                continue
            fm = read_frontmatter(full)
            if fm is None:
                continue
            parts = Path(rel).parts
            stem = Path(fn).stem
            segs = stem.split(" - ")
            ma_noi = segs[1] if len(segs) >= 3 else ""
            row = {k: fm.get(k, "") for k in FIELDS}
            row["ocr_mot_phan"] = 1 if fm.get("ocr_mot_phan") is True else 0
            row["kiem_tra_ten"] = 1 if fm.get("kiem_tra_ten") is True else 0
            people = {r: [x for x in (fm.get(r) or []) if isinstance(x, str)] for r in ROLES}
            ngay = str(row["ngay"] or "")
            tim = kd(" ".join([stem, str(row["toa"]), str(row["quan_he_phap_luat"]), str(row["so"]), ma_noi,
                               " ".join(sum(people.values(), []))]))
            con.execute("DELETE FROM nguoi WHERE path=?", (rel,))
            con.execute("INSERT OR REPLACE INTO banan VALUES (" + ",".join("?" * 26) + ")", (
                rel, mt, ma_noi, parts[0] if len(parts) > 1 else "", parts[1] if len(parts) > 2 else "",
                parts[2] if len(parts) > 3 else "", row["toa"], row["cap"], row["loai_vu_viec"], row["so"], ngay,
                int(ngay[:4]) if ngay[:4].isdigit() else None, row["loai_van_ban"], row["cap_xet_xu"],
                row["quan_he_phap_luat"], row["ocr_mot_phan"], row["kiem_tra_ten"], str(row["ma_cong"]),
                row["nguon"], row["pdf"], row["trich_xuat"], "; ".join(people["tham_phan"]),
                "; ".join(people["thu_ky"]), "; ".join(people["kiem_sat_vien"]), tim, kd(row["cap_xet_xu"])))
            con.executemany("INSERT INTO nguoi VALUES (?,?,?,?)",
                            [(rel, r, x, kd(x)) for r in ROLES for x in people[r]])
            n_new += 1
            if n_new % 2000 == 0:
                con.commit()
    gone = set(known) - seen
    for rel in gone:
        con.execute("DELETE FROM banan WHERE path=?", (rel,))
        con.execute("DELETE FROM nguoi WHERE path=?", (rel,))
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM banan").fetchone()[0]
    if not quiet:
        print(f"Chỉ mục: {vn(total)} bản án (mới/cập nhật {vn(n_new)}, bỏ {vn(len(gone))}) — {time.time() - t0:.0f} giây")
    return con


def where_clause(a):
    w, p = [], []
    if a.tham_phan or a.nguoi:
        role = "AND vai_tro='tham_phan'" if a.tham_phan else ""
        w.append(f"path IN (SELECT path FROM nguoi WHERE ten_kd LIKE ? {role})")
        p.append(f"%{kd(a.tham_phan or a.nguoi)}%")
    if a.toa:
        w.append("tim LIKE ?")
        p.append(f"%{kd(a.toa)}%")
    if a.tp:
        w.append("lower(nhom) LIKE ?")
        p.append(f"%{kd(a.tp)}%")
    if a.cap:
        w.append("lower(cap_toa) LIKE ?")
        p.append(f"%{kd(a.cap)}%")
    if a.loai:
        w.append("lower(loai_thu_muc) LIKE ?")
        p.append(f"%{kd(a.loai)}%")
    if a.qhpl:
        for word in kd(a.qhpl).split(" + "):
            w.append("tim LIKE ?")
            p.append(f"%{word}%")
    if a.so:
        w.append("so LIKE ?")
        p.append(f"%{a.so}%")
    if a.tu:
        w.append("ngay >= ?")
        p.append(a.tu if len(a.tu) > 4 else f"{a.tu}-01-01")
    if a.den:
        w.append("ngay <= ?")
        p.append(a.den if len(a.den) > 4 else f"{a.den}-12-31")
    if a.giai_doan:
        w.append("gd LIKE ?")
        p.append(f"%{kd(a.giai_doan)}%")
    return (" WHERE " + " AND ".join(w)) if w else "", p


def cmd_tim(a):
    con = capnhat(a.root, quiet=True) if a.capnhat else connect(a.root)
    w, p = where_clause(a)
    rows = con.execute(f"SELECT ngay, ma_noi, so, quan_he_phap_luat, tham_phan, path, pdf FROM banan{w} "
                       f"ORDER BY ngay DESC LIMIT ?", p + [a.limit]).fetchall()
    n = con.execute(f"SELECT COUNT(*) FROM banan{w}", p).fetchone()[0]
    print(f"Tìm thấy {vn(n)} bản án" + (f" (hiện {len(rows)} bản mới nhất)" if n > len(rows) else ""))
    for r in rows:
        print(f"- {r[0]} | {r[1]} | {r[2]} | {r[3][:70]}\n    Thẩm phán: {r[4]}\n    MD: MDBANAN/{r[5]}")
    if a.xuat:
        allrows = con.execute(f"SELECT ngay, toa, ma_noi, so, cap_xet_xu, loai_vu_viec, quan_he_phap_luat, tham_phan, "
                              f"thu_ky, kiem_sat_vien, nguon, path, pdf FROM banan{w} ORDER BY ngay", p).fetchall()
        with open(a.xuat, "w", newline="", encoding="utf-8-sig") as f:
            cw = csv.writer(f)
            cw.writerow(["Ngày", "Tòa", "Mã Nơi", "Số", "Cấp xét xử", "Loại vụ việc", "Quan hệ pháp luật",
                         "Thẩm phán", "Thư ký", "Kiểm sát viên", "Link cổng", "File MD (trong MDBANAN)", "File PDF"])
            cw.writerows(allrows)
        print(f"Đã xuất {len(allrows)} dòng ra {a.xuat}")


def cmd_thongke(a):
    con = capnhat(a.root, quiet=True) if a.capnhat else connect(a.root)
    w, p = where_clause(a)
    n = con.execute(f"SELECT COUNT(*) FROM banan{w}", p).fetchone()[0]
    print(f"Tổng: {vn(n)} bản án")
    for title, col in (("Theo năm", "nam"), ("Theo Tòa", "ma_noi"), ("Theo loại vụ việc", "loai_thu_muc"),
                       ("Theo cấp xét xử", "cap_xet_xu"), ("Quan hệ pháp luật nhiều nhất", "quan_he_phap_luat")):
        rows = con.execute(f"SELECT {col}, COUNT(*) c FROM banan{w} GROUP BY {col} ORDER BY "
                           f"{'c DESC' if col != 'nam' else 'nam'} LIMIT 15", p).fetchall()
        print(f"\n{title}:")
        for k, c in rows:
            print(f"  {k or '(trống)'}: {c}")


def cmd_nguoi(a):
    con = capnhat(a.root, quiet=True) if a.capnhat else connect(a.root)
    a.tham_phan = a.nguoi = None
    w, p = where_clause(a)
    role = a.vai_tro or "tham_phan"
    cond = (" AND " + w[len(" WHERE "):]) if w else ""
    rows = con.execute(f"SELECT n.ten, COUNT(*) c, MIN(b.ngay), MAX(b.ngay) FROM nguoi n JOIN banan b ON b.path=n.path "
                       f"WHERE n.vai_tro=?{cond} GROUP BY n.ten_kd ORDER BY c DESC LIMIT ?",
                       [role] + p + [a.limit]).fetchall()
    for ten, c, d1, d2 in rows:
        print(f"{ten}: {c} bản án ({d1} → {d2})")


def main():
    ap = argparse.ArgumentParser(description="Chỉ mục bản án MDBANAN")
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("capnhat", help="Cập nhật chỉ mục (chỉ đọc file mới/sửa)")
    for name in ("tim", "thongke", "nguoi"):
        s = sub.add_parser(name)
        s.add_argument("--tham-phan", help="Tên Thẩm phán (không cần dấu, khớp một phần)")
        s.add_argument("--nguoi", help="Tên Thẩm phán, Thư ký hoặc Kiểm sát viên")
        s.add_argument("--toa", help="Mã Nơi hoặc tên Tòa: KV3, 'quan 1', CC-HN...")
        s.add_argument("--tp", help="Nhánh: 'ho chi minh', 'ha noi', 'da nang', 'toi cao', 'cap cao'")
        s.add_argument("--cap", help="'cap tinh' hoặc 'cap huyen'")
        s.add_argument("--loai", help="Loại vụ việc: 'dan su', 'hinh su', 'hon nhan'...")
        s.add_argument("--qhpl", help="Từ khóa quan hệ pháp luật; nhiều từ nối bằng ' + '")
        s.add_argument("--so", help="Số bản án, vd 500/2024")
        s.add_argument("--giai-doan", help="'so tham', 'phuc tham', 'giam doc tham'")
        s.add_argument("--tu", help="Từ ngày: 2023 hoặc 2023-05-01")
        s.add_argument("--den", help="Đến ngày")
        s.add_argument("--limit", type=int, default=30)
        s.add_argument("--xuat", help="Xuất toàn bộ kết quả ra file CSV")
        s.add_argument("--vai-tro", help="(lệnh nguoi) tham_phan | thu_ky | kiem_sat_vien")
        s.add_argument("--capnhat", action="store_true", help="Cập nhật chỉ mục trước khi tìm")
    a = ap.parse_args()
    if a.cmd == "capnhat":
        capnhat(a.root)
    elif a.cmd == "tim":
        cmd_tim(a)
    elif a.cmd == "thongke":
        cmd_thongke(a)
    else:
        cmd_nguoi(a)


if __name__ == "__main__":
    sys.exit(main())
