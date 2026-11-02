#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""So sánh bản Mirror cũ (~/My Drive.bak-mirror) với Drive hiện tại (chế độ Stream) — CHỈ ĐỌC.

In tiến độ theo từng thư mục cấp 1; ghi danh sách file chỉ có ở bản cũ vào ~/toaan-work/chi_co_o_ban_cu.txt.
So tên file đã chuẩn hoá Unicode (NFC) để tránh báo nhầm do khác cách mã hoá dấu tiếng Việt.

  python3 compare_bak.py              # toàn bộ
  python3 compare_bak.py "003 - BOOKS"  # một thư mục
"""
import os
import sys
import time
import unicodedata
from pathlib import Path

ACC = os.environ.get("ACC", "dovietcuong.uk@gmail.com")
BAK = Path.home() / "My Drive.bak-mirror"
NEW = Path.home() / "Library" / "CloudStorage" / f"GoogleDrive-{ACC}" / "My Drive"
OUT = Path.home() / "toaan-work" / "chi_co_o_ban_cu.txt"
SKIP_EXT = (".gdoc", ".gsheet", ".gslides", ".gform", ".gdraw", ".gmap", ".gsite", ".gjam", ".gscript")
SKIP_NAME = {".DS_Store", "Icon\r", ".localized"}


def nfc(s):
    return unicodedata.normalize("NFC", s)


def files(root):
    """Tập đường dẫn tương đối (NFC) và tổng dung lượng."""
    out, size = {}, 0
    if root.is_file():
        return {nfc(root.name): root.stat().st_size}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith(".tmp")]
        for fn in fns:
            if fn in SKIP_NAME or fn.startswith("._") or fn.endswith(SKIP_EXT) or fn.startswith(".~lock"):
                continue
            p = os.path.join(dp, fn)
            try:
                s = os.lstat(p).st_size
            except OSError:
                s = 0
            out[nfc(os.path.relpath(p, root))] = s
    return out


def vn(n):
    return f"{n:,}".replace(",", ".")


def main():
    if not NEW.is_dir() or NEW.is_symlink():
        sys.exit(f"Không thấy thư mục Stream: {NEW}")
    tops = sys.argv[1:] or sorted(os.listdir(BAK))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    total_missing = total_bytes = 0
    t0 = time.time()
    with OUT.open("w", encoding="utf-8") as fo:
        for top in tops:
            if top in SKIP_NAME or top.startswith("."):
                continue
            a = files(BAK / top)
            if not a:
                continue
            new_top = NEW / top
            b = files(new_top) if new_top.exists() else {}
            # thư mục Stream có thể dùng tên NFC khác bản cũ: thử tìm theo tên đã chuẩn hoá
            if not b:
                for cand in os.listdir(NEW):
                    if nfc(cand) == nfc(top):
                        b = files(NEW / cand)
                        break
            miss = [k for k in a if k not in b]
            mb = sum(a[k] for k in miss)
            total_missing += len(miss)
            total_bytes += mb
            for k in miss:
                fo.write(f"{top}/{k}\n" if (BAK / top).is_dir() else f"{top}\n")
            fo.flush()
            print(f"[{time.time() - t0:5.0f}s] {top}: bản cũ {vn(len(a))} file, trên Drive {vn(len(b))}, "
                  f"CHỈ CÓ Ở BẢN CŨ: {vn(len(miss))} ({mb / 1e9:.2f} GB)", flush=True)
    print(f"\nTỔNG: {vn(total_missing)} file ({total_bytes / 1e9:.2f} GB) chỉ có ở bản cũ. Danh sách: {OUT}")


if __name__ == "__main__":
    main()
