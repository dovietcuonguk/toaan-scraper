#!/usr/bin/env bash
# Việc chạy một lần: liệt kê cấp xét xử và danh sách Tòa, đẩy kết quả lên Drive để phân tích.
cd /root/toaan-scraper && .venv/bin/python tools/probe_levels.py \
  && rclone copyto /root/work/probe_levels.json "gdrive:TAND CAP TINH/_TASKS/probe_levels.json"
