# -*- coding: utf-8 -*-
"""Khối thông tin đầu file MD (YAML frontmatter) cho kho bản án MDBANAN.

Dùng chung cho: tạo MD mới trên MacBook (mac/process_inbox.py), dọn và chuyển dữ liệu cũ,
và script cập nhật hằng ngày. Tách tên Thẩm phán, Thư ký, Kiểm sát viên từ phần mở đầu
bản án — tên người tiến hành tố tụng không bị ẩn khi công bố (Điều 7.3 Nghị quyết 03/2017/NQ-HĐTP).
Việc tách tên là ước lượng theo mẫu câu; bản OCR được đánh dấu kiem_tra_ten: true.
"""
import json
import re
import unicodedata

# Phần mở đầu bản án dừng ở các đề mục nội dung
_END_HEAD = re.compile(r"NH[ẬA]N TH[ẤA]Y|N[ỘO]I DUNG V[ỤU] [ÁA]N|X[ÉE]T TH[ẤA]Y|TR[ÌI]NH T[ỰU] T[ỐO] T[ỤU]NG|"
                       r"QUY[ẾE]T Đ[ỊI]NH:|NH[ẬA]N Đ[ỊI]NH C[ỦU]A", re.I)
_TITLE = re.compile(r"(?<![\wÀ-ỹ])(Ông|Bà|ông|bà|ÔNG|BÀ)\s+")
_STOP_WORDS = {"Ông", "Bà", "Sau", "Ngày", "Về", "Thẩm", "Thư", "Kiểm", "Hội", "Chủ", "Tòa", "Toà", "Viện", "Đại", "Các", "Là", "Và", "Sinh",
               "THẨM", "THƯ", "KIỂM", "HỘI", "CHỦ", "TÒA", "TOÀ", "VIỆN"}


def _clean(s):
    s = unicodedata.normalize("NFC", s or "")
    return re.sub(r"[ \t\r\f\v]+", " ", s)


def _names(seg):
    """Các họ tên đứng sau 'Ông'/'Bà' trong đoạn văn bản."""
    out = []
    for m in _TITLE.finditer(seg):
        toks = seg[m.end():m.end() + 60].split("\n", 1)[0].split()
        name = []
        for t in toks:
            w = t.strip(".,;:()–-\"“”'")
            if not w or not w[0].isupper() or not w.replace("đ", "d").isalpha() or w in _STOP_WORDS:
                break
            name.append(w)
            if t != w and t.rstrip(".,;:)") != w:  # có dấu câu đi kèm → hết tên
                break
            if t.endswith((",", ";", ".", ":")):
                break
            if len(name) >= 5:
                break
        if 2 <= len(name) <= 5:
            n = " ".join(x if not x.isupper() else x.capitalize() for x in name)
            if n not in out:
                out.append(n)
    return out


def tach_nguoi_tien_hanh_to_tung(text):
    """Trả về dict: tham_phan, thu_ky, kiem_sat_vien (danh sách họ tên)."""
    t = _clean(text)[:8000]
    m = _END_HEAD.search(t, 300)
    head = t[: m.start()] if m else t[:5000]
    res = {"tham_phan": [], "thu_ky": [], "kiem_sat_vien": []}
    # Thẩm phán: dòng có chữ "Thẩm phán" đầu tiên và các dòng liệt kê tiếp theo
    mt = re.search(r"Th[ẩâaầấ]m\s*ph[áa]n", head, re.I)
    if mt:
        ls = head.rfind("\n", 0, mt.start()) + 1
        lines = head[ls:].split("\n")
        seg = [lines[0]]
        for ln in lines[1:10]:
            x = ln.strip()
            if re.search(r"H[ộọo]i\s*th[ẩâa]m|Th[ưựu]\s*k[ýy]|Vi[ệeê]n\s*ki[ểeếê]m|Đ[ạa]i\s*di[ệe]n", x, re.I):
                break
            if x and not re.match(r"(Các|Thẩm|Thâm|THẨM|THÂM|Ông|Bà|ÔNG|BÀ|\d+[.)]|[-–+•])", x):
                break
            seg.append(ln)
        res["tham_phan"] = _names("\n".join(seg))
    mk = re.search(r"Th[ưựu]\s*k[ýy]", head, re.I)
    if mk:
        stop = re.compile(r"Đ[ạa]i\s*di[ệe]n|Vi[ệeê]n\s*ki[ểeếê]m|\n\s*\n", re.I).search(head, mk.end())
        res["thu_ky"] = _names(head[mk.start(): stop.start() if stop else mk.end() + 250])[:2]
    mv = re.search(r"Vi[ệeê]n\s*ki[ểeếê]m\s*s[áa]t", head, re.I)
    if mv:
        seg = head[mv.start(): mv.start() + 500]
        mm = re.search(r"Ki[ểeếêệ]m\s*s[áa]t\s*vi[êe]n", seg[20:], re.I)
        seg = seg[: 20 + mm.end() + 10] if mm else seg
        res["kiem_sat_vien"] = _names(seg)[:3]
    if not res["tham_phan"]:
        res["tham_phan"] = _ky_ten_cuoi(_clean(text)[-2500:])
    return res


def _ky_ten_cuoi(tail):
    """Quyết định do một Thẩm phán ký: lấy họ tên dưới dòng 'THẨM PHÁN' ở cuối văn bản."""
    m = None
    for m in re.finditer(r"TH[ẨÂA]M\s*PH[ÁA]N", tail):
        pass
    if not m:
        return []
    for ln in tail[m.end():].split("\n")[:8]:
        x = ln.strip().strip(".,;:()")
        if not x or x.startswith("(") or re.search(r"[đĐ]ã\s*k[ýy]|k[ýy]\s*t[êe]n|đ[óo]ng\s*d[ấa]u", x, re.I):
            continue
        ws = x.split()
        if 2 <= len(ws) <= 5 and all(w[0].isupper() and w.replace("đ", "d").isalpha() for w in ws):
            return [" ".join(w if not w.isupper() else w.capitalize() for w in ws)]
        break
    return []


def ngay_iso(so_ngay_toa):
    m = re.search(r"ng[àa]y\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})", so_ngay_toa or "", re.I)
    if not m:
        return ""
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{y:04d}-{mo:02d}-{d:02d}" if 1 <= d <= 31 and 1 <= mo <= 12 else ""


def so_hieu(so_ngay_toa):
    m = re.search(r"s[ốo]\s*(.+?)\s*ng[àa]y", so_ngay_toa or "", re.I)
    return re.sub(r"\s+", "", m.group(1)) if m else ""


def build(fields):
    """fields: dict theo thứ tự mong muốn → chuỗi YAML (giá trị ghi dạng JSON, hợp lệ với YAML)."""
    lines = ["---"]
    for k, v in fields.items():
        if v is None or v == "" or v == []:
            v = [] if isinstance(v, list) else ""
        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines) + "\n"
