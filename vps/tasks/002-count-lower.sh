#!/usr/bin/env bash
# Việc chạy một lần: đếm bản án từng TAND cấp huyện (cũ) và TAND khu vực của 3 thành phố; đẩy kết quả lên Drive.
cd /root/toaan-scraper && .venv/bin/python tools/count_lower.py \
  && rclone copyto /root/work/count_lower.json "gdrive:TAND CAP TINH/_TASKS/count_lower.json"
