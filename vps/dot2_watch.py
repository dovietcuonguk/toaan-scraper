#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Số liệu gọn (JSON) của một VPS cho màn hình theo dõi thời gian thực trên MacBook (tools/dot2_mac.sh theodoi)."""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dot2_status as S  # noqa: E402

WORK = S.WORK


def main():
    k, courts, listed, got, waiting, proc, methods, up_wait, md_wait = S.gather()
    now = datetime.now()
    hour_ago, recent, ok = now - timedelta(hours=1), deque(maxlen=20), 0
    last_hour = 0
    st = WORK / "state" / "processed2.csv"
    if st.exists():
        with st.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["status"] != "LOI":
                    ok += 1
                try:
                    if datetime.fromisoformat(r["timestamp"]) >= hour_ago:
                        last_hour += 1
                except ValueError:
                    pass
                recent.append(r)
    items = []
    for r in recent:
        rel, stem = r["dest_dir"], r["final_stem"]
        on_vps_pdf = (WORK / "upload2" / rel / f"{stem}.pdf").exists()
        on_vps_md = (WORK / "md2" / rel / f"{stem}.md").exists() or \
            any(p.exists() for p in (WORK / "outbox_md").glob(f"*/{rel}/{stem}.md"))
        items.append({"t": r["timestamp"], "m": r["method"], "s": r["status"], "n": stem,
                      "drive": not on_vps_pdf and r["status"] != "LOI", "mac": not on_vps_md and r["status"] != "LOI"})
    cur = ""
    lg = WORK / "logs" / "download2.log"
    if lg.exists():
        with lg.open(encoding="utf-8", errors="replace") as f:
            tail = deque(f, maxlen=30)
        for line in reversed(tail):
            m = re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \[([^\]]+)\]", line)
            if m:
                cur = m.group(1)
                break
    svc = {}
    for s in ("toaan-lower", "toaan-process2", "toaan-upload3"):
        try:
            svc[s] = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True).stdout.strip()
        except Exception:  # noqa: BLE001
            svc[s] = "?"
    print(json.dumps({
        "k": k, "now": now.isoformat(timespec="seconds"), "courts": len(courts),
        "total": sum(c["total"] for c in courts), "listed": sum(listed.values()), "got": sum(got.values()),
        "waiting": waiting, "proc": sum(proc.values()), "ok": ok, "up_wait": up_wait, "md_wait": md_wait,
        "methods": dict(methods), "last_hour": last_hour, "free_gb": round(shutil.disk_usage(str(WORK)).free / 1e9, 1),
        "cur": cur, "svc": svc, "done": (WORK / "DOT2_ALL_DONE").exists(),
        "dl_done": (WORK / "DOWNLOAD2_DONE").exists(), "recent": items,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
