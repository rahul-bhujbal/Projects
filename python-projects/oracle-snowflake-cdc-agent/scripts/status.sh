#!/usr/bin/env bash
# Connector states, task errors, and the CDC topics in Kafka.
# Git Bash on Windows: stop MSYS rewriting "/..." arguments into Windows paths.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"
set -uo pipefail
CONNECT=http://localhost:8083

for c in $(curl -fs "$CONNECT/connectors" | tr -d '[]"' | tr ',' ' '); do
  echo "== $c"
  curl -fs "$CONNECT/connectors/$c/status" \
    | sed -e 's/"trace":"[^"]*"/"trace":"(see: docker logs connect)"/g'
  echo
done

echo "== Topics"
docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list | grep -E '^sap\.' || true
