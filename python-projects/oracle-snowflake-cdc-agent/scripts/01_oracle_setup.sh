#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Prepares the Oracle container for CDC and loads the SAP SD tables:
#   1. ARCHIVELOG mode (restarts the database inside the container once)
#   2. Supplemental logging + Debezium common user c##dbzuser
#   3. SAP SD tables in schema SAPSD (skipped if they already exist)
#   4. Sample data (re-runnable: clears and reloads all 30 tables)
# Run from the project folder after: docker compose up -d
# ---------------------------------------------------------------------------
# Git Bash on Windows: stop MSYS rewriting "/..." arguments into Windows paths.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Create .env first: cp .env.example .env" >&2; exit 1; }
set -a; source .env; set +a

sysdba() { docker exec -i oracle sqlplus -s / as sysdba; }
sapsd()  { docker exec -i oracle sqlplus -s "SAPSD/${SAPSD_PASSWORD}@//localhost:1521/FREEPDB1"; }
query_sysdba() {
  printf 'SET HEADING OFF FEEDBACK OFF PAGESIZE 0 VERIFY OFF\n%s\nEXIT\n' "$1" | sysdba | tr -d '[:space:]'
}

echo "==> Waiting for Oracle to be healthy (first start takes a few minutes)"
until [ "$(docker inspect -f '{{.State.Health.Status}}' oracle 2>/dev/null)" = "healthy" ]; do
  sleep 5; printf '.'
done
echo " ok"

echo "==> 1. ARCHIVELOG mode"
if [ "$(query_sysdba 'SELECT log_mode FROM v$database;')" = "ARCHIVELOG" ]; then
  echo "Already in ARCHIVELOG mode"
else
  docker exec oracle mkdir -p /opt/oracle/oradata/recovery_area
  sysdba <<'SQL'
WHENEVER SQLERROR EXIT FAILURE
ALTER SYSTEM SET db_recovery_file_dest_size = 10G;
ALTER SYSTEM SET db_recovery_file_dest = '/opt/oracle/oradata/recovery_area' SCOPE = SPFILE;
SHUTDOWN IMMEDIATE
STARTUP MOUNT
ALTER DATABASE ARCHIVELOG;
ALTER DATABASE OPEN;
ALTER PLUGGABLE DATABASE ALL OPEN;
ALTER PLUGGABLE DATABASE ALL SAVE STATE;
EXIT
SQL
  echo "Log mode now: $(query_sysdba 'SELECT log_mode FROM v$database;')"
fi

echo "==> 2. Supplemental logging and Debezium user"
sysdba < oracle/01_debezium_user.sql

echo "==> 3. SAP SD tables"
TABLE_COUNT=$(printf 'SET HEADING OFF FEEDBACK OFF PAGESIZE 0\nSELECT COUNT(*) FROM user_tables WHERE table_name = '"'"'VBAK'"'"';\nEXIT\n' | sapsd | tr -d '[:space:]')
if [ "$TABLE_COUNT" = "1" ]; then
  echo "Tables already exist, skipping DDL"
else
  { echo "WHENEVER SQLERROR EXIT FAILURE"; cat oracle/s4_sd_oracle_ddl.sql; printf '\nEXIT\n'; } | sapsd
  echo "Tables created"
fi

echo "==> 4. Sample data"
{ echo "WHENEVER SQLERROR EXIT FAILURE"; echo "SET FEEDBACK OFF"; cat oracle/s4_sd_sample_data.sql; printf '\nEXIT\n'; } | sapsd
sapsd < oracle/91_row_counts.sql

echo "Oracle is ready for Debezium."
