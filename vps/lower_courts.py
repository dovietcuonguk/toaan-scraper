# -*- coding: utf-8 -*-
"""Danh sách TAND cấp huyện (cũ) và TAND khu vực của TP. Hồ Chí Minh, Hà Nội, Đà Nẵng cho đợt 2.

Đọc từ count_lower.json (tools/count_lower.py, trên VPS: /root/work/count_lower.json) hoặc từ danh mục
_danh_muc_toa_an.json (tools/build_court_catalog.py, trong MDBANAN). Tính "mã Nơi" dùng trong tên file.
"""
import json
import re
import unicodedata
from pathlib import Path

CITY_CODE = {"tp-hcm": "HCM", "ha-noi": "HN", "da-nang": "ĐN"}
CITY_DIR = {"tp-hcm": "TP HO CHI MINH", "ha-noi": "HA NOI", "da-nang": "DA NANG"}
CITY_OF_TEXT = {"Hồ Chí Minh": "tp-hcm", "Hà Nội": "ha-noi", "Đà Nẵng": "da-nang"}


def short_name(name):
    n = unicodedata.normalize("NFC", name.strip())
    m = re.search(r"khu vực\s*(\d+)", n, re.I)
    if m:
        return f"KV{m.group(1)}"
    n = re.sub(r"^(TAND|Tòa án nhân dân)\s+", "", n)
    if re.match(r"(thành phố|TP\.)\s*", n, re.I):
        return "TP " + re.sub(r"^(thành phố|TP\.)\s*", "", n, flags=re.I).strip()
    return re.sub(r"^(Q\.|huyện|thị xã|TX\.)\s*", "", n, flags=re.I).strip()


def load(path, cities):
    """Trả về danh sách dict: value, name, city, kind ('huyen'|'khu-vuc'), total, ma_noi."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    if isinstance(d, dict):  # count_lower.json
        rows = list(d.values())
    else:  # _danh_muc_toa_an.json
        rows = []
        for r in d:
            if r.get("cap") != "H" or not r.get("pham_vi_kho") or r.get("pham_vi_kho") == "False":
                continue
            city = next((v for k, v in CITY_OF_TEXT.items() if r.get("tinh_thanh", "").endswith(k)), None)
            rows.append({"value": r["ma_cong"], "name": r["ten"], "city": city,
                         "kind": "khu-vuc" if "khu vực" in r.get("loai", "") else "huyen",
                         "total": int(r["so_ban_an"]) if str(r.get("so_ban_an", "")).isdigit() else 0})
    for r in rows:
        if r.get("city") not in cities or not r.get("total"):
            continue
        r = dict(r)
        r["ma_noi"] = f"{CITY_CODE[r['city']]}-{short_name(r['name'])}"
        out.append(r)
    out.sort(key=lambda r: (r["city"], r["kind"], -r["total"]))
    return out


def _kd(s):
    s = unicodedata.normalize("NFD", (s or "").replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower()


def case_type_of(rec):
    """Loại vụ việc (khóa dùng trong CASE_TYPE_DIR) từ trường 'loai_vu_viec' của bản ghi trên cổng."""
    t = _kd(rec.get("loai_vu_viec") or rec.get("loai_vu_viec_loc") or "")
    for key, pat in (("xu-ly-hanh-chinh", "xu ly hanh chinh"), ("hinh-su", "hinh su"),
                     ("hon-nhan-gia-dinh", "hon nhan"), ("kinh-doanh-thuong-mai", "kinh doanh"),
                     ("lao-dong", "lao dong"), ("pha-san", "pha san"), ("hanh-chinh", "hanh chinh"),
                     ("dan-su", "dan su")):
        if pat in t:
            return key
    return "khac"


def shard(courts, n):
    """Chia Tòa cho n máy theo tổng số bản án (LPT, tất định): Tòa lớn trước, mỗi Tòa vào máy đang ít nhất.
    Trả về list n phần tử, mỗi phần tử là list Tòa (giữ thứ tự của `courts`)."""
    groups, sums = [[] for _ in range(n)], [0] * n
    for c in sorted(courts, key=lambda c: (-c["total"], str(c["value"]))):
        k = min(range(n), key=lambda i: (sums[i], i))
        groups[k].append(c["value"])
        sums[k] += c["total"]
    pos = {v: k for k, g in enumerate(groups) for v in g}
    out = [[] for _ in range(n)]
    for c in courts:
        out[pos[c["value"]]].append(c)
    return out


def parse_shard(s):
    """'2/3' -> (2, 3)."""
    k, n = (int(x) for x in s.split("/"))
    if not 1 <= k <= n:
        raise ValueError(f"shard không hợp lệ: {s}")
    return k, n


def shard_summary(courts, n):
    lines = []
    for k, g in enumerate(shard(courts, n), 1):
        by = {}
        for c in g:
            by[c["city"]] = by.get(c["city"], 0) + c["total"]
        tot = sum(c["total"] for c in g)
        lines.append(f"VPS{k}: {fmt(tot)} bản án / {len(g)} Tòa ("
                     + ", ".join(f"{CITY_CODE[ct]} {fmt(by.get(ct, 0))}" for ct in ("tp-hcm", "ha-noi", "da-nang"))
                     + ")")
    return "\n".join(lines)


def fmt(n):
    return f"{n:,}".replace(",", ".")


if __name__ == "__main__":  # python3 vps/lower_courts.py /root/work/count_lower.json [số máy]
    import sys
    cs = load(sys.argv[1], ["tp-hcm", "ha-noi", "da-nang"])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(f"{len(cs)} Tòa, {fmt(sum(c['total'] for c in cs))} bản án")
    print(shard_summary(cs, n))
    for k, g in enumerate(shard(cs, n), 1):
        print(f"\n== VPS{k} ==")
        for c in g:
            print(f"  {c['value']:>6}  {c['ma_noi']:<28} {c['kind']:<8} {fmt(c['total']):>7}")
