#!/bin/bash
# Generate crontab from config and start supercronic
#
# Reads schedule.hour, schedule.minute, and schedule.day_of_week from
# config.yaml via a small Python snippet, then writes the crontab.

set -e

SCHEDULE=$(python -c "
from src.config import load_config
c = load_config()
# cron day_of_week: 0=Sunday. Python config: 0=Monday.
# Convert: Python Saturday=5 -> cron Saturday=6
cron_dow = (c.schedule.day_of_week + 1) % 7
print(f'{c.schedule.minute} {c.schedule.hour} * * {cron_dow}')
" 2>/dev/null || echo "0 6 * * 6")

echo "${SCHEDULE} cd /app && python -m src.main run >> /app/logs/cron.log 2>&1" > /app/crontab

echo "Schedule: ${SCHEDULE} (from config)"
echo "Starting supercronic..."

exec supercronic /app/crontab
