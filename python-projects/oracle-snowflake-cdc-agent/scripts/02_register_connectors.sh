#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Creates or updates both connectors on Kafka Connect (idempotent: PUT).
#   ./scripts/02_register_connectors.sh          both connectors
#   ./scripts/02_register_connectors.sh source   Debezium Oracle source only
#   ./scripts/02_register_connectors.sh sink     Snowflake sink only
# ---------------------------------------------------------------------------
# Git Bash on Windows: stop MSYS rewriting "/..." arguments into Windows paths.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

CONNECT=http://localhost:8083
WHICH="${1:-all}"

echo "==> Waiting for Kafka Connect"
until curl -fs "$CONNECT/connector-plugins" > /tmp/plugins.json 2>/dev/null; do sleep 3; printf '.'; done
echo " ok"
for plugin in io.debezium.connector.oracle.OracleConnector \
              com.snowflake.kafka.connector.SnowflakeStreamingSinkConnector; do
  grep -q "$plugin" /tmp/plugins.json || { echo "Plugin missing: $plugin (rebuild: docker compose build connect)" >&2; exit 1; }
done

put_connector() {   # name, config file
  echo "==> $1"
  curl -fsS -X PUT -H "Content-Type: application/json" \
       --data @"$2" "$CONNECT/connectors/$1/config" > /dev/null
  sleep 5
  curl -fsS "$CONNECT/connectors/$1/status"; echo
}

if [ "$WHICH" = "all" ] || [ "$WHICH" = "source" ]; then
  put_connector sap-sd-oracle-source connectors/oracle-source.json
fi

if [ "$WHICH" = "all" ] || [ "$WHICH" = "sink" ]; then
  [ -f snowflake/secrets/snowflake.properties ] || {
    echo "Missing snowflake/secrets/snowflake.properties - run snowflake/generate_snowflake_keys.sh" >&2; exit 1; }
  case "$SNOWFLAKE_URL" in *"<"*|"") echo "Set SNOWFLAKE_URL in .env" >&2; exit 1;; esac
  sed "s|__SNOWFLAKE_URL__|${SNOWFLAKE_URL}|" connectors/snowflake-sink.json > connectors/snowflake-sink.rendered.json
  put_connector sap-sd-snowflake-sink connectors/snowflake-sink.rendered.json
fi

echo "Check status any time: ./scripts/status.sh"
