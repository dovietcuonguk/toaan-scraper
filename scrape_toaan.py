#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrape_toaan.py
================
Thu thập danh sách bản án/quyết định công khai trên
https://congbobanan.toaan.gov.vn theo từng loại vụ/việc.

Với MỖI bản án/quyết định, script lưu lại:
  - Các trường siêu dữ liệu có cấu trúc: số/ngày, tòa án, quan hệ pháp luật,
    cấp xét xử, loại vụ/việc, áp dụng án lệ, đính chính...
  - Toàn văn trường "Thông tin về vụ/việc" (tóm tắt/toàn văn nội dung do
    Tòa án công bố kèm theo bản án).
  - Đường link trang chi tiết (để script fetch_pdfs.py tải file PDF gốc sau).

Vì trang này không có API công khai (ASP.NET WebForms, phân trang bằng
postback), script dùng Playwright để điều khiển một trình duyệt Chromium
thật, chọn bộ lọc, rồi "nhảy trang" bằng dropdown chọn số trang có sẵn
trên giao diện (không cần bấm "Trang sau" tuần tự).

CÁCH DÙNG (xem thêm README.md):
  python scrape_toaan.py --case-type dan-su --max-records 500

Script có checkpoint (--resume) và ghi từng trang ngay khi xử lý xong, nên
có thể dừng (Ctrl+C) và chạy lại bất cứ lúc nào mà không mất dữ liệu đã tải.
"""

import argparse
import json
import logging
import re
import signal
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit(
        "Thiếu thư viện playwright. Cài đặt bằng:\n"
        "  pip install -r requirements.txt\n"
        "  python -m playwright install chromium"
    )

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Thiếu thư viện beautifulsoup4. Cài đặt bằng: pip install -r requirements.txt")


BASE_URL = "https://congbobanan.toaan.gov.vn"
LISTING_URL = f"{BASE_URL}/0tat1cvn/ban-an-quyet-dinh"

# Nhãn hiển thị trên trang <-> khóa dùng trên dòng lệnh (không dấu, dễ gõ)
CASE_TYPES = {
    "hinh-su": "Hình sự",
    "dan-su": "Dân sự",
    "hon-nhan-gia-dinh": "Hôn nhân và gia đình",
    "kinh-doanh-thuong-mai": "Kinh doanh thương mại",
    "hanh-chinh": "Hành chính",
    "lao-dong": "Lao động",
    "pha-san": "Quyết định tuyên bố phá sản",
    "xu-ly-hanh-chinh": "Quyết định áp dụng biện pháp xử lý hành chính",
}

# Bộ lọc "Cấp xét xử" — xác định bằng kiểm tra trực tiếp form tìm kiếm ngày
# 2026-09-16 (dropdown #Drop_Levels): "" =-----chọn----- (tất cả cấp),
# "TW" = TAND tối cao, "CW" = TAND cấp cao (gộp cả 3 tòa: Hà Nội, Đà Nẵng,
# TP.HCM — không cần chọn thêm tòa cụ thể ở dropdown phụ thuộc
# #Ra_Drop_Courts để lấy đủ cả 3), "T" = TAND cấp tỉnh, "H" = TAND cấp huyện.
# Không dùng "" làm khóa CLI (khó phân biệt với "không truyền tham số") nên
# chỉ định nghĩa 2 khóa cần dùng ở đây.
LEVELS = {
    "toi-cao": ("TW", "TAND tối cao"),
    "cap-cao": ("CW", "TAND cấp cao"),
    # TAND cấp tỉnh: dùng kèm --court-value để chọn đúng một Tòa trong dropdown
    # phụ thuộc Ra_Drop_Courts (đã kiểm chứng trên VPS ngày 31/10/2026:
    # 787 = TAND TP. Hồ Chí Minh, 784 = TAND TP. Hà Nội, 775 = TAND TP Đà Nẵng).
    "tinh": ("T", "TAND cấp tỉnh"),
}

# Bộ chọn dự phòng ("main") — dùng khi vì lý do nào đó (đổi giao diện, đổi
# breakpoint responsive...) bộ "_top" không còn hiển thị được nữa.
FALLBACK_SEL = {
    "case_type": "#ctl00_Content_home_Public_ctl00_Drop_CASES_STYLES_SEARCH",
    "search_btn": "#ctl00_Content_home_Public_ctl00_cmd_Left_search",
    "level": "#ctl00_Content_home_Public_ctl00_Drop_Levels",
    "date_from": "#ctl00_Content_home_Public_ctl00_Rad_DATE_FROM",
    "date_to": "#ctl00_Content_home_Public_ctl00_Rad_DATE_TO",
}

# Các "id" thẻ HTML lấy được bằng cách kiểm tra trực tiếp trang tìm kiếm
# (ngày 2026-09-16). Nếu Tòa án nhân dân tối cao đổi giao diện, các id này
# có thể phải cập nhật lại.
SEL = {
    # Trang này render 2 bộ điều khiển tìm kiếm trùng id gốc (một bộ "_top"
    # nằm trong thanh tìm kiếm nhanh phía trên, một bộ "chính" nằm trong
    # bảng điều kiện tìm kiếm mở rộng). Ở độ rộng màn hình desktop mặc định
    # mà Playwright dùng (1280x720), CHỈ bộ "_top" thực sự hiển thị — bộ
    # "chính" bị ẩn (display:none) qua CSS responsive, khiến select_option()/
    # click() báo lỗi "Timeout... element is not visible". Do đó dùng bộ
    # "_top" cho phần chọn bộ lọc + bấm tìm kiếm (đã kiểm tra thực tế ngày
    # 16/09/2026, đúng cho viewport desktop chuẩn).
    "case_type": "#ctl00_Content_home_Public_ctl00_Drop_CASES_STYLES_SEARCH_top",
    "search_btn": "#ctl00_Content_home_Public_ctl00_cmd_search_banner",
    "level": "#ctl00_Content_home_Public_ctl00_Drop_Levels_top",
    "page_select": "#ctl00_Content_home_Public_ctl00_DropPages",
    "results": "#List_group_pub",
    "results_items": "#List_group_pub .list-group-item",
    "total_label": "#ctl00_Content_home_Public_ctl00_lbl_count_record",
    # Bộ lọc "Tìm kiếm theo khoảng thời gian ban hành" (đã kiểm chứng trực
    # tiếp trên form ngày 2026-09-17: nhãn ghi rõ "ban hành", và lọc thử
    # với "Từ ngày" = 01/09/2026 cho TAND tối cao + Dân sự trả về đúng 3
    # bản ghi, toàn bộ có ngày ban hành >= 01/09/2026 — xác nhận lọc theo
    # NGÀY BAN HÀNH, không phải ngày công bố lên cổng thông tin).
    "date_from": "#ctl00_Content_home_Public_ctl00_Rad_DATE_FROM_top",
    "date_to": "#ctl00_Content_home_Public_ctl00_Rad_DATE_TO_top",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

ID_RE = re.compile(r"/2ta(\d+)t1cvn/")


def build_logger(log_path: Path) -> logging.Logger:
    log = logging.getLogger("toaan")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


def field_value(item_soup: BeautifulSoup, label_text: str):
    """Tìm <label>label_text</label> rồi lấy text của <span> đi kèm ngay sau."""
    label = item_soup.find("label", string=re.compile(re.escape(label_text)))
    if not label:
        return None
    sib = label.find_next_sibling("span")
    if sib is not None:
        return sib.get_text(" ", strip=True)
    # fallback: đôi khi span nằm trong cùng thẻ cha, không phải sibling trực tiếp
    parent_text = label.parent.get_text(" ", strip=True)
    return parent_text.replace(label.get_text(strip=True), "").strip() or None


def parse_item(div) -> dict:
    a = div.select_one("a.echo_id_pub")
    href = urljoin(BASE_URL, a["href"]) if a and a.get("href") else None
    rec_id = None
    if href:
        m = ID_RE.search(href)
        if m:
            rec_id = m.group(1)

    heading = div.select_one("h4.list-group-item-heading")
    loai_van_ban = None
    so_ngay_toa = None
    ngay_cong_bo = None
    if heading:
        lbl = heading.find("label")
        if lbl:
            loai_van_ban = lbl.get_text(strip=True).rstrip(":")
        span = heading.find("span")
        if span:
            span_copy = BeautifulSoup(str(span), "html.parser")
            time_tag = span_copy.find("time")
            if time_tag:
                ngay_cong_bo = time_tag.get_text(strip=True).strip("()")
                time_tag.extract()
            so_ngay_toa = span_copy.get_text(" ", strip=True)

    desc_span = div.select_one("p.Description_pub span")
    thong_tin_vu_viec = desc_span.get_text(" ", strip=True) if desc_span else None

    return {
        "id": rec_id,
        "url_chi_tiet": href,
        "loai_van_ban": loai_van_ban,           # "Bản án" hoặc "Quyết định"
        "so_ngay_toa": so_ngay_toa,              # vd: "số 502 ngày 16/07/2026 của TAND tỉnh Đồng Nai"
        "ngay_cong_bo": ngay_cong_bo,             # ngày công bố trên cổng thông tin
        "quan_he_phap_luat": field_value(div, "Quan hệ pháp luật"),
        "cap_xet_xu": field_value(div, "Cấp xét xử"),
        "ap_dung_an_le": field_value(div, "Áp dụng án lệ"),
        "loai_vu_viec": field_value(div, "Loại vụ/việc"),
        "dinh_chinh": field_value(div, "Đính chính"),
        "thong_tin_vu_viec": thong_tin_vu_viec,
    }


def dismiss_popups(page) -> None:
    """Trang có vài overlay hay chặn thao tác click:
    - #popModal: khảo sát "bạn làm nghề gì?" hiện lên có độ trễ sau khi tải trang,
      data-backdrop="static" nên không tắt được bằng click ra ngoài/phím Esc.
    - Widget thông báo đẩy của SendPulse (chèn qua script bên thứ 3).

    NGUYÊN NHÂN GỐC (xác định qua log ground-truth ngày 16/09/2026, sau khi
    gắn page.on("response")/page.on("pageerror") để bắt trực tiếp): bên
    trong #popModal có UpdatePanel 'ctl00_Feedback_Home_Ajax_Manager_Updata'
    (bảng câu hỏi khảo sát nghề nghiệp). Server trả kèm một đoạn cập nhật
    cho ĐÚNG panel này ở NGAY ĐẦU của hầu như MỌI phản hồi postback bất
    đồng bộ trên trang — kể cả phản hồi cho việc đổi "Loại vụ/việc" lẫn
    phản hồi cho việc bấm "Tìm kiếm" (đã thấy trực tiếp: body dài tới
    1.4MB, tức có chứa cả nội dung kết quả tìm kiếm thật, nhưng đoạn xử lý
    ĐẦU TIÊN vẫn là panel khảo sát). Bản cũ của hàm này XÓA HẲN #popModal
    khỏi DOM (.remove()) để đóng popup — khiến UpdatePanel bên trong cũng
    biến mất theo. Khi phản hồi sau đó cố áp dụng đoạn cập nhật cho panel
    không còn tồn tại, Sys.WebForms.PageRequestManager ném ngoại lệ
    "Could not find UpdatePanel..." ngay tại đoạn ĐẦU TIÊN của chuỗi phản
    hồi (định dạng pipe-delimited, xử lý TUẦN TỰ) — làm hỏng luôn việc áp
    dụng các đoạn cập nhật CÒN LẠI phía sau, bao gồm cả đoạn cập nhật danh
    sách kết quả tìm kiếm THẬT SỰ nằm sau đó trong CÙNG phản hồi. Đây là lý
    do "Tìm kiếm" luôn thất bại 100% dù server vẫn trả đúng dữ liệu.

    => SỬA: chỉ ẨN #popModal bằng CSS (display:none) và gỡ trạng thái mở
    (class 'modal-open' trên <body>, các lớp phủ 'modal-backdrop'), TUYỆT
    ĐỐI KHÔNG xóa khỏi DOM, để UpdatePanel bên trong luôn được framework
    tìm thấy. Widget SendPulse thì vẫn xóa hẳn vì nó là script bên thứ ba,
    không nằm trong aspnetForm/UpdatePanel nào của trang."""
    try:
        page.evaluate(
            """
            () => {
              const modal = document.getElementById('popModal');
              if (modal) {
                modal.style.display = 'none';
                modal.setAttribute('aria-hidden', 'true');
                modal.classList.remove('in', 'show');
              }
              document.querySelectorAll('.modal-backdrop').forEach(el => { el.style.display = 'none'; });
              document.body.classList.remove('modal-open');
              document.querySelectorAll('[id^="sp-"], [class*="sp-backdrop"], [class*="sp-message"]')
                .forEach(el => el.remove());
            }
            """
        )
    except Exception:
        pass  # không quan trọng nếu lần gọi nào đó không có gì để dọn


def _select_case_type_and_settle(page, sel_id: str, case_label: str, log: logging.Logger) -> None:
    """Dropdown 'Loại vụ/việc' có AutoPostBack=true — mỗi lần đổi giá trị,
    trang TỰ gửi một postback AJAX (UpdatePanel) riêng, độc lập với việc bấm
    nút 'Tìm kiếm' sau đó. Nếu bấm 'Tìm kiếm' trong lúc postback ngầm này
    CHƯA xong, hai postback chồng lên nhau khiến PageRequestManager của
    trang lỗi ('Could not find UpdatePanel...') và postback tìm kiếm bị huỷ
    ngang — không có bản ghi nào hiện ra, không có ngoại lệ nào lộ ra phía
    Playwright để báo.

    LƯU Ý: page.wait_for_load_state("networkidle") KHÔNG dùng được để chờ
    việc này — trạng thái đó gắn với lần điều hướng (navigation) gần nhất.
    Trang đã đạt "networkidle" ngay từ sau page.goto() ban đầu, nên gọi lại
    hàm này sau một XHR phát sinh về sau gần như trả về ngay lập tức, không
    thực sự chờ gì cả (đã kiểm chứng qua log thực tế: khoảng cách thời gian
    giữa hai dòng log đúng bằng 25s — đúng bằng timeout của bước chờ kết quả
    phía sau, tức là bước chờ 'networkidle' này không tiêu tốn giây nào).

    Thay vào đó, dùng page.expect_response() bọc quanh chính hành động
    select_option() để Playwright bắt đúng request POST hậu trường (async
    postback) gửi tới cùng URL trang, rồi mới cho phép thao tác tiếp."""
    try:
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.split("?")[0].rstrip("/") == LISTING_URL.rstrip("/"),
            timeout=10000,
        ):
            page.select_option(sel_id, label=case_label)
        # Response về rồi không có nghĩa là DOM đã cập nhật xong ngay — client
        # (Sys.WebForms.PageRequestManager) còn cần một khoảnh khắc để parse
        # và áp dụng nội dung mới. Nghỉ thêm một chút cho chắc.
        page.wait_for_timeout(1500)
    except PWTimeout:
        log.warning(
            "  Không bắt được postback ngầm sau khi đổi loại vụ/việc "
            "(có thể do trùng giá trị cũ) — nghỉ cố định 2.5s để an toàn."
        )
        page.wait_for_timeout(2500)


def _select_level_and_settle(page, sel_id: str, level_value: str, log: logging.Logger) -> None:
    """Y hệt cơ chế của _select_case_type_and_settle ở trên (cùng một dạng
    dropdown AutoPostBack=true), áp dụng cho dropdown 'Cấp xét xử'. Đã kiểm
    chứng trực tiếp trên trình duyệt thật ngày 16/09/2026: chọn 'CW' (TAND
    cấp cao) làm dropdown phụ thuộc #Ra_Drop_Courts tự nạp lại 3 tòa (Hà
    Nội/Đà Nẵng/TP.HCM) — không cần chọn thêm gì ở đó để lấy đủ cả 3, vì để
    trống ("-----chọn-----") ở #Ra_Drop_Courts nghĩa là "tất cả tòa thuộc
    cấp đã chọn". Chọn theo value (TW/CW), không theo label, vì đây là mã
    cố định của hệ thống."""
    try:
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.split("?")[0].rstrip("/") == LISTING_URL.rstrip("/"),
            timeout=10000,
        ):
            page.select_option(sel_id, value=level_value)
        page.wait_for_timeout(1500)
    except PWTimeout:
        log.warning(
            "  Không bắt được postback ngầm sau khi đổi cấp xét xử "
            "(có thể do trùng giá trị cũ) — nghỉ cố định 2.5s để an toàn."
        )
        page.wait_for_timeout(2500)


def select_level(page, level_value: str, log: logging.Logger) -> None:
    """Chọn cấp xét xử, ưu tiên bộ điều khiển '_top', tự chuyển sang bộ
    'main' nếu '_top' không hiển thị — cùng logic với select_case_type()."""
    try:
        page.wait_for_selector(SEL["level"], state="visible", timeout=8000)
        _select_level_and_settle(page, SEL["level"], level_value, log)
        return
    except PWTimeout:
        log.warning("Bộ lọc cấp xét xử '_top' không hiển thị, thử bộ điều khiển chính (fallback)...")
        page.wait_for_selector(FALLBACK_SEL["level"], state="visible", timeout=15000)
        SEL["level"] = FALLBACK_SEL["level"]
        _select_level_and_settle(page, FALLBACK_SEL["level"], level_value, log)


def select_court(page, court_value: str, log: logging.Logger, top: bool = True) -> str:
    """Chọn một Tòa cụ thể trong dropdown phụ thuộc '...Drop_Courts...' (được nạp
    lại sau khi chọn cấp xét xử). top=True: bộ '_top' (hiển thị); top=False: bộ
    'chính' (ẩn, dùng ở nhánh fallback). Trả về nhãn Tòa đã chọn; ném lỗi nếu
    không tìm thấy giá trị (tránh âm thầm tải nhầm toàn bộ Tòa cấp tỉnh)."""
    info = page.evaluate(
        """([value, wantTop]) => {
            const sels = Array.from(document.querySelectorAll('select'))
              .filter(s => /Drop_Courts/i.test(s.id) && (s.id.endsWith('_top') === wantTop));
            for (const s of sels) {
              const opt = Array.from(s.options).find(o => o.value === value);
              if (opt) return {id: s.id, text: opt.text.trim(),
                               visible: !!(s.offsetWidth || s.offsetHeight || s.getClientRects().length)};
            }
            return null;
        }""",
        [court_value, top],
    )
    if not info:
        raise RuntimeError(f"Không tìm thấy Tòa có mã {court_value} trong dropdown chọn Tòa (top={top})")
    sel_id = "#" + info["id"]
    if info["visible"]:
        try:
            with page.expect_response(
                lambda r: r.request.method == "POST" and r.url.split("?")[0].rstrip("/") == LISTING_URL.rstrip("/"),
                timeout=10000,
            ):
                page.select_option(sel_id, value=court_value)
        except PWTimeout:
            pass
        page.wait_for_timeout(1500)
    else:
        _set_select_value_js(page, sel_id, court_value)
        page.wait_for_timeout(1000)
    log.info(f"Chọn Tòa: {info['text']} (mã {court_value}, {info['id']})")
    return info["text"]


def _set_select_value_js(page, sel_id: str, value: str, by_label: bool = False) -> None:
    """Chọn giá trị cho <select> bằng JS trực tiếp, KHÔNG qua page.select_option()
    của Playwright.

    LÝ DO (kiểm chứng trực tiếp trên trình duyệt thật, 2026-09-19): bộ điều
    khiển dự phòng (FALLBACK_SEL) nằm trong panel
    '#ctl00_..._search_content', panel này có display:none CỐ ĐỊNH ở
    viewport desktop (1280x720) mà script dùng — KHÔNG PHẢI ẩn theo
    responsive/chiều rộng màn hình như dòng comment cũ của SEL/FALLBACK_SEL
    suy đoán. page.select_option()/page.click() của Playwright đòi hỏi phần
    tử phải "visible" nên luôn báo Timeout ở đây (đã thấy thực tế: 45s
    timeout, 87 lần thử lại 'element is not visible'). Gán giá trị trực
    tiếp qua thuộc tính DOM rồi phát sự kiện 'change' vẫn kích hoạt đúng
    handler phía trang dù phần tử đang ẩn — đã kiểm chứng: ra đúng
    lbl_count_record='0' cho tổ hợp biết trước là 0 bản ghi."""
    page.evaluate(
        """
        ([selId, value, byLabel]) => {
            const el = document.querySelector(selId);
            if (!el) throw new Error('Không tìm thấy phần tử: ' + selId);
            if (byLabel) {
                const opt = Array.from(el.options).find((o) => o.textContent.trim() === value);
                if (!opt) throw new Error('Không tìm thấy option nhãn: ' + value);
                el.value = opt.value;
            } else {
                el.value = value;
            }
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """,
        [sel_id, value, by_label],
    )


def _click_js(page, sel_id: str) -> None:
    """Bấm phần tử bằng JS .click() trực tiếp — bỏ qua yêu cầu 'visible' của
    Playwright. Dùng cho các phần tử thuộc panel dự phòng luôn bị ẩn (xem
    _set_select_value_js ở trên)."""
    page.evaluate(
        """
        (selId) => {
            const el = document.querySelector(selId);
            if (!el) throw new Error('Không tìm thấy phần tử: ' + selId);
            el.click();
        }
        """,
        sel_id,
    )


def _set_text_value_js(page, sel_id: str, value: str) -> None:
    """Gán giá trị cho một ô nhập text bằng đúng cơ chế đã KIỂM CHỨNG THỰC
    TẾ là hoạt động đúng trên trang này (browser thật, 2026-09-17): dùng
    property setter GỐC của HTMLInputElement (native setter, không qua bất
    kỳ getter/setter tuỳ biến nào của trang) rồi phát 3 sự kiện input/change/
    blur.

    LÝ DO KHÔNG DÙNG page.fill(): đã dùng page.fill() trước đó — hàm chạy
    không lỗi, log vẫn in đúng giá trị đã "điền", NHƯNG kết quả tìm kiếm sau
    đó vẫn ra số bản ghi y hệt như KHÔNG lọc theo ngày (đã đối chiếu trực
    tiếp qua scrape.log thực tế ngày 2026-09-18: filter 01/07/2025 và
    01/09/2026 cho ra tổng số bản ghi gần như giống hệt nhau — tức giá trị
    field không thực sự "ăn" vào lúc submit, dù DOM báo đã có giá trị ngay
    sau khi gọi fill()). Thay bằng chính đoạn JS đã kiểm chứng qua
    page.evaluate() — hai lần thử độc lập trên trình duyệt thật đều cho kết
    quả lọc đúng — để loại trừ hẳn sự khác biệt hành vi giữa fill() và một
    thao tác nhập liệu thật."""
    page.evaluate(
        """
        ([selId, value]) => {
            const el = document.querySelector(selId);
            if (!el) throw new Error('Không tìm thấy phần tử: ' + selId);
            el.focus();
            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeSetter.call(el, value);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        }
        """,
        [sel_id, value],
    )


def fill_date_range(page, date_from: str | None, date_to: str | None, log: logging.Logger) -> None:
    """Điền bộ lọc "Tìm kiếm theo khoảng thời gian ban hành" (Từ ngày/Đến
    ngày, định dạng dd/MM/yyyy). Khác với các dropdown ở trên, đây là ô
    nhập text thường — gán giá trị KHÔNG tự kích hoạt postback nào (không
    giống dropdown AutoPostBack=true); bộ lọc chỉ thực sự áp dụng khi bấm
    nút "Tìm kiếm" ngay sau đó."""
    if not date_from and not date_to:
        return
    sel_from, sel_to = SEL["date_from"], SEL["date_to"]
    try:
        page.wait_for_selector(sel_from, state="visible", timeout=8000)
    except PWTimeout:
        log.warning("Ô 'Từ ngày' _top không hiển thị, thử bộ điều khiển chính (fallback)...")
        sel_from, sel_to = FALLBACK_SEL["date_from"], FALLBACK_SEL["date_to"]
        page.wait_for_selector(sel_from, state="visible", timeout=15000)
        SEL["date_from"], SEL["date_to"] = sel_from, sel_to
    if date_from:
        log.info(f"Điền 'Từ ngày' (ban hành): {date_from}")
        _set_text_value_js(page, sel_from, date_from)
    if date_to:
        log.info(f"Điền 'Đến ngày' (ban hành): {date_to}")
        _set_text_value_js(page, sel_to, date_to)
    # Cho trang một khoảnh khắc ổn định trước khi bấm "Tìm kiếm" — cùng mức
    # thận trọng đã áp dụng cho các dropdown khác (_select_*_and_settle).
    page.wait_for_timeout(500)


def select_case_type(page, case_label: str, log: logging.Logger) -> None:
    """Chọn loại vụ/việc, ưu tiên bộ điều khiển '_top' (hiển thị ở độ rộng
    desktop mặc định), tự động chuyển sang bộ 'main' nếu '_top' không hiển thị."""
    try:
        page.wait_for_selector(SEL["case_type"], state="visible", timeout=8000)
        _select_case_type_and_settle(page, SEL["case_type"], case_label, log)
        return
    except PWTimeout:
        log.warning("Bộ lọc '_top' không hiển thị, thử bộ điều khiển chính (fallback)...")
        page.wait_for_selector(FALLBACK_SEL["case_type"], state="visible", timeout=15000)
        SEL["search_btn"] = FALLBACK_SEL["search_btn"]  # đồng bộ nút bấm theo cùng bộ
        _select_case_type_and_settle(page, FALLBACK_SEL["case_type"], case_label, log)


def click_search(page, log: logging.Logger) -> None:
    dismiss_popups(page)
    try:
        page.wait_for_selector(SEL["search_btn"], state="visible", timeout=8000)
        dismiss_popups(page)
        page.click(SEL["search_btn"])
    except PWTimeout:
        log.warning("Nút 'Tìm kiếm' đang dùng không hiển thị, thử bộ điều khiển chính (fallback)...")
        page.wait_for_selector(FALLBACK_SEL["search_btn"], state="visible", timeout=15000)
        dismiss_popups(page)
        page.click(FALLBACK_SEL["search_btn"])


def jump_to_page(page, page_num: int, log: logging.Logger, retries: int = 3) -> bool:
    """NGUYÊN NHÂN LỖI CŨ (xác định bằng kiểm tra trực tiếp trên trình duyệt
    thật ngày 16/09/2026): đổi dropdown DropPages hoạt động đúng — nội dung
    trang THẬT SỰ đổi — nhưng cần tới ~20 giây mới có phản hồi (cùng lý do
    server chậm như bước bấm "Tìm kiếm"). page.wait_for_load_state("networkidle")
    không chờ được XHR phát sinh SAU khi trang đã "networkidle" (bug y hệt đã
    gặp ở bước tìm kiếm). Còn page.wait_for_selector(results_items) thì luôn
    "thấy" ngay các mục CŨ — chúng vẫn còn nguyên trong DOM cho tới khi nội
    dung mới thật sự được áp dụng — nên hàm tưởng đã xong và trả về ngay,
    khiến run() luôn đọc lại đúng nội dung trang trước đó (đã kiểm chứng: cả
    28 lần "nhảy trang" trong một lần chạy thật đều trả về y hệt 20 bản ghi
    của trang 1, không hề có postback POST nào được gửi lên kịp trước khi đọc).

    SỬA: dùng page.expect_response() để chờ đúng postback thật sự hoàn tất
    (như đã áp dụng cho dropdown "Loại vụ/việc"), sau đó xác nhận NỘI DUNG đã
    đổi thật (so sánh link của mục đầu tiên trước/sau) thay vì chỉ kiểm tra
    sự tồn tại của phần tử khớp selector."""
    for attempt in range(1, retries + 1):
        try:
            dismiss_popups(page)
            try:
                before_href = page.locator(SEL["results_items"] + " a.echo_id_pub").first.get_attribute(
                    "href", timeout=2000
                )
            except PWTimeout:
                before_href = None

            with page.expect_response(
                lambda r: r.request.method == "POST" and r.url.split("?")[0].rstrip("/") == LISTING_URL.rstrip("/"),
                timeout=60000,
            ):
                page.select_option(SEL["page_select"], value=str(page_num))

            # Chờ tới khi mục đầu tiên đổi hẳn so với trước — xác nhận nội
            # dung trang mới đã thực sự được áp dụng vào DOM, không chỉ dựa
            # vào việc phần tử khớp selector đã "tồn tại" (mục cũ vẫn còn đó).
            page.wait_for_function(
                """(prevHref) => {
                    const a = document.querySelector('#List_group_pub a.echo_id_pub');
                    return !!a && a.getAttribute('href') !== prevHref;
                }""",
                arg=before_href,
                timeout=45000,
            )
            return True
        except PWTimeout:
            log.warning(f"  Timeout khi nhảy tới trang {page_num} (lần {attempt}/{retries})")
            time.sleep(3)
        except Exception as e:  # option chưa tồn tại, lỗi DOM tạm thời, v.v.
            log.warning(f"  Lỗi khi nhảy tới trang {page_num} (lần {attempt}/{retries}): {e}")
            time.sleep(3)
    return False


def load_seen_ids(records_path: Path) -> set:
    seen = set()
    if not records_path.exists():
        return seen
    with records_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rid = json.loads(line).get("id")
                if rid:
                    seen.add(rid)
            except json.JSONDecodeError:
                continue
    return seen


def run(args):
    case_label = CASE_TYPES[args.case_type]
    level_value, level_label = LEVELS[args.level] if args.level else (None, None)
    if args.out_dir:
        out_dir = Path(args.out_dir)
    elif args.level:
        # Thư mục riêng cho dữ liệu đã lọc theo cấp xét xử, KHÔNG dùng chung
        # với data/<case-type> mặc định (vốn chứa dữ liệu "tất cả các cấp"
        # đã thu thập trước đó) — tránh trộn hai phạm vi khác nhau vào cùng
        # một records.jsonl/checkpoint.
        out_dir = Path("data") / args.level / args.case_type
    else:
        out_dir = Path("data") / args.case_type
    out_dir.mkdir(parents=True, exist_ok=True)

    records_path = out_dir / "records.jsonl"
    checkpoint_path = out_dir / "checkpoint.json"
    log = build_logger(out_dir / "scrape.log")

    seen_ids = load_seen_ids(records_path)
    start_page = args.start_page
    if args.resume and checkpoint_path.exists():
        try:
            cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            # Bảo vệ khỏi trộn nhầm phạm vi lọc: một checkpoint ghi từ lần
            # chạy KHÔNG lọc theo ngày (hoặc lọc ngày khác) không còn khớp
            # số trang/tổng bản ghi của lần chạy hiện tại (vd: chạy giám sát
            # hàng tuần dùng --date-from cố định trên cùng out-dir cũ) — nếu
            # cứ resume theo last_page_done cũ sẽ bỏ sót/đọc sai trang.
            cp_date_from = cp.get("date_from")
            cp_date_to = cp.get("date_to")
            if (cp_date_from != args.date_from or cp_date_to != args.date_to
                    or cp.get("court_value") != args.court_value):
                log.warning(
                    f"Checkpoint cũ ứng với bộ lọc ngày khác "
                    f"(từ={cp_date_from!r}, đến={cp_date_to!r}) so với lần chạy này "
                    f"(từ={args.date_from!r}, đến={args.date_to!r}) — bỏ qua checkpoint, "
                    "bắt đầu lại từ trang 1 (records đã có vẫn được giữ nguyên nhờ seen_ids)."
                )
            else:
                start_page = max(start_page, cp.get("last_page_done", 0) + 1)
                log.info(f"Resume: tiếp tục từ trang {start_page} (checkpoint: {checkpoint_path})")
        except Exception as e:
            log.warning(f"Không đọc được checkpoint ({e}), bắt đầu từ trang {start_page}")

    stop_flag = {"stop": False}
    # Cờ đánh dấu phiên chạy KẾT THÚC DỞ DANG do lỗi (mất mạng, jump_to_page
    # hết lượt thử lại...) — KHÔNG do người dùng chủ động Ctrl+C và KHÔNG do
    # đạt --max-records/hết trang. Trước đây các nhánh lỗi này chỉ log.error()
    # rồi break/return bình thường, khiến tiến trình thoát với exit code 0 y
    # hệt một phiên chạy thành công trọn vẹn — script gọi (vd: run_all_remaining.sh)
    # tưởng lầm là "xong", chuyển ngay sang tổ hợp tiếp theo, để lại tổ hợp này
    # dở dang mà không ai biết cho tới khi có người tự kiểm tra checkpoint.json
    # thủ công. Nay: mọi nhánh lỗi loại này bật cờ này lên, và cuối hàm sẽ
    # sys.exit(1) thay vì thoát êm — để exit code phản ánh đúng sự thật.
    incomplete = False

    def handle_sigint(signum, frame):
        if stop_flag["stop"]:
            log.warning("Nhận Ctrl+C lần 2 — thoát ngay.")
            sys.exit(1)
        log.warning("Nhận Ctrl+C — sẽ dừng an toàn sau khi lưu xong trang hiện tại...")
        stop_flag["stop"] = True

    signal.signal(signal.SIGINT, handle_sigint)

    total_saved_this_run = 0
    court_re = re.compile(args.court_regex, re.I) if args.court_regex else None

    with sync_playwright() as p:
        # --disable-blink-features=AutomationControlled: tắt cờ mà Chromium tự
        # bật khi bị Playwright/Selenium điều khiển (đặt navigator.webdriver =
        # true và vài dấu hiệu khác). Nhiều WAF/CDN của các trang lớn (đặc
        # biệt trang nhà nước, lưu lượng cao) fingerprint automation qua các
        # dấu hiệu này — KHÔNG chặn hẳn (vẫn trả 200), mà âm thầm trả về một
        # phản hồi AJAX bị cắt/hỏng cho các phiên bị nghi là bot, rất khớp với
        # hiện tượng đang gặp: script luôn thất bại 100% (10/10 lần, y hệt
        # nhau) trong khi thao tác thủ công y hệt trên trình duyệt thật (không
        # bị đặt navigator.webdriver) thỉnh thoảng vẫn thành công.
        browser = p.chromium.launch(
            headless=args.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=USER_AGENT, locale="vi-VN", viewport={"width": 1280, "height": 800}
        )
        # Phòng thêm: ẩn navigator.webdriver ở mức JS ngay từ đầu mỗi trang,
        # đúng vị trí mà chính công cụ automation-detection kiểm tra trước
        # tiên. Chạy trước MỌI script khác của trang (add_init_script).
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = window.chrome || { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
            """
        )
        # Chặn hẳn widget thông báo đẩy của bên thứ 3 (SendPulse) — nó chèn một
        # lớp overlay hay chặn click, không liên quan gì đến chức năng tra cứu.
        context.route(re.compile(r"sendpulse\.com"), lambda route: route.abort())
        page = context.new_page()
        page.set_default_timeout(45000)

        # Ba fix trước (chờ đúng postback ngầm, tải lại trang sạch mỗi lần
        # thử, giả lập trình duyệt thật) đều KHÔNG giải quyết được — script
        # vẫn thất bại 100% ở máy thật của người dùng. Thay vì tiếp tục đoán
        # từ ảnh chụp/HTML tĩnh, gắn thẳng 3 "tai nghe" vào trang để ghi lại
        # SỰ THẬT xảy ra ngay trong lần chạy tới, vào thẳng scrape.log:
        #   (1) dialog  — có confirm()/alert() nào bị bật lên (do
        #       check_validate_top() coi như "chưa chọn tiêu chí") và bị
        #       Playwright tự động đóng âm thầm hay không;
        #   (2) console — mọi console.error/warn của trang, đặc biệt ngoại lệ
        #       "Could not find UpdatePanel..." đã từng thấy khi tái hiện thủ công;
        #   (3) pageerror — mọi lỗi JS không bắt được (uncaught exception);
        #   (4) response — nội dung thô của MỌI phản hồi POST gửi tới đúng
        #       URL trang tìm kiếm, để biết postback bấm "Tìm kiếm" có thực
        #       sự được gửi lên server hay không, và nếu có thì server trả
        #       về gì (đoạn pipe-delimited của ASP.NET AJAX có chứa cập nhật
        #       cho #List_group_pub hay không, hay báo lỗi/redirect ẩn).
        def _on_dialog(dialog):
            log.warning(
                f"[DIALOG] type={dialog.type} message={dialog.message!r} "
                "— tự động đóng (accept) để không treo trình duyệt."
            )
            try:
                dialog.accept()
            except Exception:
                pass

        def _on_console(msg):
            if msg.type in ("error", "warning"):
                log.warning(f"[CONSOLE:{msg.type}] {msg.text}")

        def _on_pageerror(exc):
            log.warning(f"[PAGEERROR] {exc}")

        def _on_response(response):
            try:
                if response.request.method != "POST":
                    return
                if response.url.split("?")[0].rstrip("/") != LISTING_URL.rstrip("/"):
                    return
                body = response.text()
                # Kiểm tra nhanh các "dấu vết" quan trọng có mặt trong phản hồi
                # hay không — để biết chắc server có gửi đúng nội dung (panel
                # khảo sát / panel tìm kiếm+kết quả / báo lỗi) hay không, độc
                # lập với việc trình duyệt có ÁP DỤNG được các đoạn đó hay không.
                markers = [
                    key
                    for key in (
                        "Feedback_Home_Ajax_Manager_Updata",
                        "Content_home_Public",
                        "List_group_pub",
                        "lbl_count_record",
                        "pageRedirect",
                    )
                    if key in body
                ]
                log.info(
                    f"[XHR POST] status={response.status} body_len={len(body)} dấu_vết={markers}\n"
                    f"  --- 2000 ký tự đầu của phản hồi ---\n  {body[:2000]!r}"
                )
            except Exception as e:
                log.warning(f"[XHR POST] không đọc được nội dung phản hồi: {e}")

        page.on("dialog", _on_dialog)
        page.on("console", _on_console)
        page.on("pageerror", _on_pageerror)
        page.on("response", _on_response)

        # Trang này thỉnh thoảng lỗi AJAX ngay giữa lúc xử lý postback tìm
        # kiếm (đã xác nhận qua console: "Sys.InvalidOperationException:
        # Could not find UpdatePanel with ID 'ctl00_Feedback_Home_Ajax_
        # Manager_Updata'" — một UpdatePanel không liên quan (khảo sát nghề
        # nghiệp) được cấu hình tự cập nhật kèm MỌI postback trên trang; khi
        # lỗi này xảy ra, nó làm hỏng toàn bộ phần xử lý phản hồi postback đó
        # — kể cả phần cập nhật danh sách kết quả — dù Playwright không thấy
        # ngoại lệ nào cả). Đã kiểm chứng trực tiếp: một khi lỗi này xảy ra,
        # PHÍA CLIENT của trang (Sys.WebForms.PageRequestManager) coi như bị
        # kẹt — bấm lại "Tìm kiếm" trên CÙNG một trang không bao giờ tự phục
        # hồi được, dù đợi bao lâu. Vì vậy mỗi lần thử lại phải TẢI LẠI TRANG
        # từ đầu (page.reload/goto) để có một phiên AJAX sạch, chứ không chỉ
        # bấm lại nút trên trang cũ.
        MAX_SEARCH_ATTEMPTS = 3
        results_ok = False
        for attempt in range(1, MAX_SEARCH_ATTEMPTS + 1):
            if attempt == 1:
                log.info(f"Mở trang tìm kiếm: {LISTING_URL}")
                page.goto(LISTING_URL, wait_until="networkidle")
            else:
                log.warning(f"  Tải lại trang sạch trước khi thử lại (lần {attempt}/{MAX_SEARCH_ATTEMPTS})...")
                page.reload(wait_until="networkidle")
            dismiss_popups(page)

            if level_value:
                log.info(f"Chọn cấp xét xử: {level_label} ({level_value})")
                select_level(page, level_value, log)
                dismiss_popups(page)
            if args.court_value:
                select_court(page, args.court_value, log, top=True)
                dismiss_popups(page)

            log.info(f"Chọn loại vụ/việc: {case_label}")
            select_case_type(page, case_label, log)
            if args.date_from or args.date_to:
                fill_date_range(page, args.date_from, args.date_to, log)
            click_search(page, log)
            try:
                # Sau khi sửa lỗi "Could not find UpdatePanel" (dismiss_popups
                # không còn xóa #popModal khỏi DOM), log ground-truth ngày
                # 16/09/2026 cho thấy: KHÔNG còn ngoại lệ JS nào cả — nhưng
                # với loại vụ/việc "Dân sự" (loại nhiều bản án nhất trong 8
                # loại), server dựng lại panel kết quả rất chậm (phản hồi
                # thực đo được nặng 1.4MB, về sau ~24 giây kể từ lúc bấm, tức
                # là VƯỢT mức chờ 15 giây cũ trước khi kịp áp dụng vào DOM).
                # Tăng lên 60 giây để có đủ biên độ cho các loại vụ/việc lớn.
                page.wait_for_selector(SEL["results_items"], timeout=60000)
                results_ok = True
                break
            except PWTimeout:
                log.warning(
                    f"Chưa thấy kết quả sau khi bấm 'Tìm kiếm' (lần {attempt}/{MAX_SEARCH_ATTEMPTS}) — "
                    "có thể trang bị lỗi AJAX tạm thời (site quá tải / postback bị lỗi phía "
                    "server). Sẽ tải lại trang sạch rồi thử lại..."
                )
                time.sleep(min(3 * attempt, 20))
        if not results_ok:
            # SỬA (2026-09-19, kiểm chứng trực tiếp trên trình duyệt thật):
            # "Chưa thấy kết quả" sau MAX_SEARCH_ATTEMPTS lần thử qua bộ '_top'
            # KHÔNG PHẢI lúc nào cũng là "site quá tải" — với một số tổ hợp mà
            # tổng số bản ghi THỰC SỰ bằng 0 (đã xác nhận trực tiếp: TAND cấp
            # cao VÀ TAND tối cao đều có đúng 0 "Quyết định áp dụng biện pháp
            # xử lý hành chính" — loại quyết định này trong thực tế hầu như chỉ
            # do TAND cấp huyện/tỉnh ban hành), bộ '_top' luôn ném ngoại lệ phía
            # client (Sys.ParameterCountException: Parameter count mismatch,
            # xem console) ngay sau khi bấm "Tìm kiếm", khiến lbl_count_record
            # không bao giờ được cập nhật (mãi để trống) — results_items dĩ
            # nhiên cũng không bao giờ xuất hiện vì có 0 mục để hiển thị. Đây
            # là lỗi có thật, LẶP LẠI 100% MỖI LẦN, không phải ngẫu nhiên.
            #
            # Bộ điều khiển "chính" (FALLBACK_SEL) submit toàn trang (full
            # postback, không qua AJAX UpdatePanel) nên KHÔNG dính lỗi này —
            # đã kiểm chứng trực tiếp: cùng tổ hợp trên, bộ này render đúng
            # "Kết quả tìm kiếm: 0 bản án, quyết định" và lbl_count_record="0".
            # Trước khi coi là lỗi thật, thử lại đúng MỘT lần bằng bộ này.
            log.warning(
                f"Không thấy kết quả qua bộ điều khiển '_top' sau {MAX_SEARCH_ATTEMPTS} "
                "lần thử. Thử lại LẦN CUỐI bằng bộ điều khiển 'chính' (submit toàn "
                "trang) — có thể tổng số bản ghi THỰC SỰ bằng 0, không phải site quá tải."
            )
            try:
                page.reload(wait_until="networkidle")
                dismiss_popups(page)
                if level_value:
                    log.info(f"  [fallback] Chọn cấp xét xử: {level_label} ({level_value})")
                    _set_select_value_js(page, FALLBACK_SEL["level"], level_value)
                    page.wait_for_timeout(1000)
                    dismiss_popups(page)
                if args.court_value:
                    page.wait_for_timeout(2000)
                    select_court(page, args.court_value, log, top=False)
                    dismiss_popups(page)
                log.info(f"  [fallback] Chọn loại vụ/việc: {case_label}")
                _set_select_value_js(page, FALLBACK_SEL["case_type"], case_label, by_label=True)
                page.wait_for_timeout(1000)
                if args.date_from or args.date_to:
                    log.info(
                        f"  [fallback] Điền khoảng ngày ban hành: "
                        f"{args.date_from or '...'} - {args.date_to or '...'}"
                    )
                    if args.date_from:
                        _set_text_value_js(page, FALLBACK_SEL["date_from"], args.date_from)
                    if args.date_to:
                        _set_text_value_js(page, FALLBACK_SEL["date_to"], args.date_to)
                    page.wait_for_timeout(500)
                dismiss_popups(page)
                with page.expect_navigation(wait_until="networkidle", timeout=30000):
                    _click_js(page, FALLBACK_SEL["search_btn"])
                dismiss_popups(page)
                SEL["search_btn"] = FALLBACK_SEL["search_btn"]
                # KHÔNG chờ results_items ở đây — nếu tổng số bản ghi thực sự
                # bằng 0 thì results_items sẽ KHÔNG BAO GIỜ xuất hiện (đúng
                # thiết kế, không phải lỗi). Xác nhận thành công bằng cách đọc
                # trực tiếp total_label — ném lỗi nếu vẫn không đọc được, rơi
                # xuống nhánh lỗi thật bên dưới như cũ.
                fallback_total = page.locator(SEL["total_label"]).first.inner_text()
                results_ok = True
                log.info(
                    f"  [fallback] Đọc được lbl_count_record='{fallback_total}' qua "
                    "bộ 'chính' — coi như thành công (kể cả khi bằng 0)."
                )
            except Exception as e:
                log.warning(f"  [fallback] Lần thử cuối bằng bộ điều khiển 'chính' cũng lỗi: {e}")

        if not results_ok:
            debug_png = out_dir / "debug_failure.png"
            debug_html = out_dir / "debug_failure.html"
            try:
                page.screenshot(path=str(debug_png), full_page=True)
                debug_html.write_text(page.content(), encoding="utf-8")
                log.error(
                    f"Đã lưu ảnh chụp + HTML lúc lỗi vào:\n  {debug_png}\n  {debug_html}\n"
                    "Gửi 2 file này (nhất là ảnh .png) để xem trang đang dừng ở trạng thái nào."
                )
            except Exception as e:
                log.error(f"Không chụp được ảnh debug: {e}")
            browser.close()
            sys.exit(
                "Không nhận được kết quả tìm kiếm sau nhiều lần thử (kể cả lần thử "
                "cuối bằng bộ điều khiển 'chính'). "
                "Xem file debug_failure.png / debug_failure.html vừa được lưu trong --out-dir."
            )

        total_text = page.locator(SEL["total_label"]).first.inner_text()
        total_records = int(re.sub(r"\D", "", total_text) or "0")
        total_pages = (total_records + 19) // 20
        scope_desc = f"loại '{case_label}'" + (f", cấp '{level_label}'" if level_label else "")
        if args.date_from or args.date_to:
            scope_desc += f", ban hành từ {args.date_from or '...'} đến {args.date_to or '...'}"
        log.info(f"Tổng cộng: {total_records} bản ghi / {total_pages} trang cho {scope_desc}")

        end_page = args.end_page or total_pages
        if args.max_records:
            # ước lượng rộng rãi: 20 bản ghi / trang, cộng thêm vài trang dự phòng
            end_page = min(end_page, start_page + max(1, args.max_records // 20) + 2)

        if start_page > total_pages:
            log.info("start-page vượt quá tổng số trang hiện có — không còn gì để tải.")
            browser.close()
            return

        if start_page > 1:
            log.info(f"Nhảy tới trang bắt đầu: {start_page}")
            if not jump_to_page(page, start_page, log):
                log.error(
                    "Không nhảy được tới trang bắt đầu — phiên chạy KHÔNG hoàn tất. "
                    "Thoát với exit code khác 0 để không bị hiểu nhầm là thành công."
                )
                browser.close()
                sys.exit(1)

        page_num = start_page
        with records_path.open("a", encoding="utf-8") as fout:
            while page_num <= end_page and not stop_flag["stop"]:
                try:
                    html = page.locator(SEL["results"]).inner_html()
                except PWTimeout:
                    log.error(f"Timeout đọc nội dung trang {page_num}, thử tải lại...")
                    page.reload(wait_until="networkidle")
                    if not jump_to_page(page, page_num, log):
                        log.error(f"Bỏ qua trang {page_num} sau nhiều lần lỗi — phiên chạy sẽ KHÔNG được tính là hoàn tất.")
                        incomplete = True
                        page_num += 1
                        continue
                    html = page.locator(SEL["results"]).inner_html()

                soup = BeautifulSoup(html, "html.parser")
                items = soup.select(".list-group-item")
                new_count = 0
                wrong_court = 0
                for div in items:
                    rec = parse_item(div)
                    if court_re and not court_re.search(unicodedata.normalize("NFC", rec.get("so_ngay_toa") or "")):
                        wrong_court += 1
                        continue
                    if not rec["id"] or rec["id"] in seen_ids:
                        continue
                    rec["loai_vu_viec_loc"] = case_label
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    seen_ids.add(rec["id"])
                    new_count += 1
                fout.flush()
                if wrong_court:
                    log.warning(f"  Trang {page_num}: bỏ qua {wrong_court}/{len(items)} mục không thuộc Tòa đã chọn")
                    if items and wrong_court == len(items):
                        log.error("Toàn bộ trang không thuộc Tòa đã chọn — bộ lọc Tòa không ăn. Dừng để tránh tải nhầm.")
                        incomplete = True
                        break
                total_saved_this_run += new_count
                log.info(
                    f"Trang {page_num}/{end_page} ({len(items)} mục hiển thị): "
                    f"+{new_count} bản ghi mới (tổng phiên này: {total_saved_this_run})"
                )

                checkpoint_path.write_text(
                    json.dumps(
                        {
                            "case_type": args.case_type,
                            "level": args.level,
                            "date_from": args.date_from,
                            "date_to": args.date_to,
                            "court_value": args.court_value,
                            "last_page_done": page_num,
                            "total_pages": total_pages,
                            "total_records_on_site": total_records,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

                if args.max_records and (len(seen_ids)) >= args.max_records:
                    log.info(f"Đã đạt --max-records={args.max_records}, dừng lại.")
                    break

                page_num += 1
                if page_num <= end_page and not stop_flag["stop"]:
                    time.sleep(args.delay)
                    if not jump_to_page(page, page_num, log):
                        log.error(
                            f"Không nhảy được tới trang {page_num} — dừng script giữa chừng, "
                            "phiên chạy sẽ KHÔNG được tính là hoàn tất."
                        )
                        incomplete = True
                        break

        browser.close()

    log.info(
        f"{'Kết thúc phiên chạy (DỞ DANG)' if incomplete else 'Hoàn tất phiên chạy'}. "
        f"+{total_saved_this_run} bản ghi mới. "
        f"Tổng cộng hiện có trong file: {len(seen_ids)}. Dữ liệu tại: {records_path}"
    )
    if incomplete:
        log.error(
            "Phiên chạy này DỪNG GIỮA CHỪNG do lỗi mạng/nhảy trang (xem log phía trên) — "
            "checkpoint.json đã lưu đúng tiến độ, chạy lại với --resume để tiếp tục. "
            "Thoát với exit code 1 để script gọi (vd: run_all_remaining.sh) không hiểu nhầm là đã xong."
        )
        sys.exit(1)


def parse_args():
    ap = argparse.ArgumentParser(
        description="Thu thập danh sách bản án/quyết định từ congbobanan.toaan.gov.vn"
    )
    ap.add_argument(
        "--case-type",
        required=True,
        choices=sorted(CASE_TYPES.keys()),
        help="Loại vụ/việc cần tải. Xem README.md để biết bảng đối chiếu.",
    )
    ap.add_argument(
        "--level",
        default=None,
        choices=sorted(LEVELS.keys()),
        help=(
            "Lọc theo cấp xét xử (mặc định: không lọc, lấy tất cả các cấp). "
            "'toi-cao' = TAND tối cao (~7.470 bản ghi mọi loại án); "
            "'cap-cao' = TAND cấp cao, gộp cả 3 tòa Hà Nội/Đà Nẵng/TP.HCM "
            "(~35.578 bản ghi mọi loại án, đã kiểm chứng trực tiếp trên "
            "form tìm kiếm ngày 16/09/2026)."
        ),
    )
    ap.add_argument("--court-value", default=None,
                    help="Mã Tòa trong dropdown chọn Tòa (dùng với --level tinh), vd 787 = TAND TP. Hồ Chí Minh")
    ap.add_argument("--court-regex", default=None,
                    help="Biểu thức kiểm tra tên Tòa trong 'so_ngay_toa'; bản ghi không khớp sẽ bị bỏ qua")
    ap.add_argument("--start-page", type=int, default=1, help="Trang bắt đầu (mặc định 1)")
    ap.add_argument("--end-page", type=int, default=None, help="Trang kết thúc (mặc định: hết)")
    ap.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="Giới hạn tổng số bản ghi mới cần lưu trong lần chạy này (dùng để chạy thử/pilot)",
    )
    ap.add_argument("--out-dir", type=str, default=None, help="Thư mục lưu dữ liệu (mặc định data/<case-type>)")
    ap.add_argument(
        "--date-from",
        type=str,
        default=None,
        metavar="dd/MM/yyyy",
        help=(
            "Chỉ lấy bản án/quyết định có NGÀY BAN HÀNH >= ngày này (đã kiểm chứng "
            "trực tiếp trên form tìm kiếm ngày 2026-09-17: nhãn 'Tìm kiếm theo khoảng "
            "thời gian ban hành', không phải ngày công bố lên cổng thông tin). "
            "Định dạng bắt buộc dd/MM/yyyy, ví dụ 01/09/2026."
        ),
    )
    ap.add_argument(
        "--date-to",
        type=str,
        default=None,
        metavar="dd/MM/yyyy",
        help="Chỉ lấy bản án/quyết định có ngày ban hành <= ngày này. Định dạng dd/MM/yyyy.",
    )
    ap.add_argument("--delay", type=float, default=1.5, help="Số giây nghỉ giữa mỗi trang (mặc định 1.5s)")
    ap.add_argument("--resume", action="store_true", help="Tiếp tục từ checkpoint lần chạy trước")
    ap.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        default=True,
        help="Chạy Chromium ẩn (mặc định bật)",
    )
    ap.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Hiện cửa sổ trình duyệt (hữu ích khi cần gỡ lỗi)",
    )
    args = ap.parse_args()
    date_re = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    for field in ("date_from", "date_to"):
        val = getattr(args, field)
        if val and not date_re.match(val):
            ap.error(f"--{field.replace('_', '-')} phải theo định dạng dd/MM/yyyy, ví dụ 01/09/2026 (nhận được: {val!r})")
    return args


if __name__ == "__main__":
    run(parse_args())
