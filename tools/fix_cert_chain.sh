#!/usr/bin/env bash
# congbobanan.toaan.gov.vn chỉ gửi chứng chỉ của chính nó, KHÔNG gửi kèm chứng chỉ trung gian
# (GlobalSign RSA OV SSL CA 2018), nên curl/python báo "unable to get local issuer certificate".
# Script này tải chứng chỉ trung gian theo địa chỉ ghi trong chính chứng chỉ của trang (AIA),
# rồi thêm vào kho chứng chỉ của hệ điều hành. Chạy bằng root.
set -u
H=congbobanan.toaan.gov.vn
DEST=/usr/local/share/ca-certificates/congbobanan-intermediate.crt

leaf=$(timeout 20 openssl s_client -connect "$H:443" -servername "$H" </dev/null 2>/dev/null \
        | openssl x509 2>/dev/null)
if [ -z "$leaf" ]; then echo "Không lấy được chứng chỉ của $H"; exit 1; fi

aia=$(printf '%s\n' "$leaf" | openssl x509 -noout -ext authorityInfoAccess 2>/dev/null \
        | grep -o 'CA Issuers - URI:[^ ]*' | head -1 | sed 's/CA Issuers - URI://')
[ -z "$aia" ] && aia="http://secure.globalsign.com/cacert/gsrsaovsslca2018.crt"
echo "Tải chứng chỉ trung gian: $aia"

tmp=$(mktemp)
curl -fsS --max-time 30 "$aia" -o "$tmp" || { echo "Không tải được chứng chỉ trung gian"; exit 1; }
# File tải về thường ở dạng DER; chuyển sang PEM (nếu đã là PEM thì giữ nguyên)
if openssl x509 -inform DER -in "$tmp" -out "$DEST" 2>/dev/null || openssl x509 -in "$tmp" -out "$DEST" 2>/dev/null; then
  update-ca-certificates >/dev/null 2>&1
  echo "Đã thêm chứng chỉ trung gian vào kho chứng chỉ hệ thống."
else
  echo "File tải về không phải chứng chỉ hợp lệ"; exit 1
fi
rm -f "$tmp"
