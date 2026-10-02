#!/bin/bash
# TTT daily data refresh — runs every facet + deploys. Scheduled via Windows Task Scheduler at 3 AM
# (after the 2 AM nflverse ingest it depends on). Logs to /tmp/ttt_refresh.log.
cd "/mnt/c/Users/Chuks/Documents/NFL DATA (real)/fantasy_app" || exit 1
LOG=/tmp/ttt_refresh.log
echo "" >> "$LOG"; echo "===================== TTT refresh $(date) =====================" >> "$LOG"
python3 pipeline/refresh_all.py --deploy >> "$LOG" 2>&1
echo "===================== done $(date) =====================" >> "$LOG"
