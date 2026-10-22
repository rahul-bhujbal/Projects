#!/usr/bin/env bash
# Applies a batch of business changes in Oracle (oracle/90_test_changes.sql),
# to watch them flow through Kafka into Snowflake.
# Git Bash on Windows: stop MSYS rewriting "/..." arguments into Windows paths.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
{ echo "WHENEVER SQLERROR EXIT FAILURE"; cat oracle/90_test_changes.sql; printf '\nEXIT\n'; } \
  | docker exec -i oracle sqlplus -s "SAPSD/${SAPSD_PASSWORD}@//localhost:1521/FREEPDB1"
echo "Changes committed at $(date '+%H:%M:%S'). Check Snowflake in about a minute."
