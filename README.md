# toaan-scraper

Mã nguồn tải bản án, quyết định đã công bố trên congbobanan.toaan.gov.vn, chạy bằng GitHub Actions.

Repo này **chỉ chứa mã nguồn**. Không lưu nội dung bản án ở đây: dữ liệu được đẩy thẳng vào Google Drive riêng của chủ repo.
Theo chân trang của congbobanan.toaan.gov.vn, việc đăng tải, phát hành lại thông tin, dữ liệu từ trang này phải có văn bản đồng ý của TANDTC.

## Chạy trên VPS Việt Nam (TAND cấp tỉnh TP. Hồ Chí Minh, Hà Nội, Đà Nẵng)

Cổng congbobanan chặn IP nước ngoài (GitHub Actions bị cắt kết nối), nên việc tải chạy trên VPS đặt tại Việt Nam.
Cổng không gửi kèm chứng chỉ trung gian GlobalSign, nên `tools/fix_cert_chain.sh` bổ sung chứng chỉ này vào máy.

Đăng nhập VPS bằng `ssh -L 53682:127.0.0.1:53682 root@<IP>` rồi chạy:

    curl -fsSL https://raw.githubusercontent.com/dovietcuonguk/toaan-scraper/main/vps/setup.sh -o setup.sh && bash setup.sh

- `vps/download.py`: lấy danh sách + tải PDF (loại vụ việc lớn chia theo năm ban hành), dịch vụ `toaan-download`.
- `vps/process_loop.sh` + `vps/process.py`: trích văn bản/OCR tiếng Việt → MD, đẩy PDF + MD lên
  `CONGBOBANAN/TAND CAP TINH/<TÒA>/<NN LOẠI VỤ VIỆC>/{PDF,MD}` trên Google Drive, dịch vụ `toaan-process`.
- Tiến độ: `CONGBOBANAN/TAND CAP TINH/_TIEN_DO.md` trên Drive, hoặc `bash vps/status.sh` trên VPS.

## Đợt 2 — TAND cấp huyện + TAND khu vực, 3 VPS (phương án A, từ 03/11/2026)

Mỗi VPS tải một nhóm Tòa (`vps/lower_courts.py shard`, chia theo tổng số bản án), đặt tên + tạo MD
(`vps/process2.py`, chỉ đọc lớp chữ; bản scan gắn `can_ocr: true` để OCR sau trên MacBook), đẩy PDF thẳng lên
Google Drive `BANAN PDF/<TP>/CAP HUYEN - KHU VUC/<LOẠI>/` (`vps/upload3.sh`, remote rclone `banan` dùng OAuth Client ID riêng).
MacBook kéo MD về `MDBANAN/` cùng cây thư mục. Điều khiển cả 3 máy từ MacBook bằng `tools/dot2_mac.sh`:

    curl -fsSL https://raw.githubusercontent.com/dovietcuonguk/toaan-scraper/main/tools/dot2_mac.sh -o ~/dot2_mac.sh
    bash ~/dot2_mac.sh            # xem danh sách lệnh

Tiến độ từng máy: `BANAN PDF/_TIEN_DO_DOT2/TIEN_DO_VPS<k>.md` (30 phút/lần) hoặc `bash ~/dot2_mac.sh tiendo`.
