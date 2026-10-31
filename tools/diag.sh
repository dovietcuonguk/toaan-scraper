#!/usr/bin/env bash
# Chẩn đoán vì sao máy chủ không truy cập được congbobanan.toaan.gov.vn
#   curl -fsSL https://raw.githubusercontent.com/dovietcuonguk/toaan-scraper/main/tools/diag.sh | bash
H=congbobanan.toaan.gov.vn
URL="https://$H/0tat1cvn/ban-an-quyet-dinh"

echo "== 1. Phân giải tên miền (DNS) =="
getent ahosts "$H" | awk '{print $1}' | sort -u || echo "LỖI DNS"

echo; echo "== 2. Mở cổng 443 (TCP) =="
for ip in $(getent ahostsv4 "$H" | awk '{print $1}' | sort -u); do
  if timeout 10 bash -c "</dev/tcp/$ip/443" 2>/dev/null; then echo "$ip:443 MỞ"; else echo "$ip:443 KHÔNG KẾT NỐI ĐƯỢC"; fi
done

echo; echo "== 3. Bắt tay TLS (openssl) =="
timeout 20 openssl s_client -connect "$H:443" -servername "$H" </dev/null 2>&1 \
  | grep -E "CONNECTED|Verify return code|Protocol|Cipher is|errno|error|s:|i:" | head -12

echo; echo "== 4. curl bình thường (kiểm tra chứng chỉ) =="
curl -sS -o /dev/null -w 'HTTP %{http_code}  thời gian %{time_total}s\n' --max-time 60 -A "Mozilla/5.0" "$URL" 2>&1 | tail -2

echo; echo "== 5. curl bỏ qua kiểm tra chứng chỉ (-k) =="
curl -k -sS -o /dev/null -w 'HTTP %{http_code}  thời gian %{time_total}s\n' --max-time 60 -A "Mozilla/5.0" "$URL" 2>&1 | tail -2

echo; echo "== 6. curl ép IPv4, HTTP/1.1 =="
curl -4 --http1.1 -k -sS -o /dev/null -w 'HTTP %{http_code}  thời gian %{time_total}s\n' --max-time 60 -A "Mozilla/5.0" "$URL" 2>&1 | tail -2

echo; echo "== 7. Đối chứng: trang khác của Tòa án =="
curl -k -sS -o /dev/null -w 'toaan.gov.vn: HTTP %{http_code}\n' --max-time 30 https://www.toaan.gov.vn/ 2>&1 | tail -1
curl -sS -o /dev/null -w 'google.com: HTTP %{http_code}\n' --max-time 30 https://www.google.com/ 2>&1 | tail -1
