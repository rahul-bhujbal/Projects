#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Generates the RSA key pair for the Snowflake Kafka connector service user.
#
# Outputs (in ./secrets unless a folder is passed as the first argument):
#   sf_kafka_key.p8            private key (PKCS#8, unencrypted) - keep secret
#   sf_kafka_key.pub           public key
#   snowflake.properties       private.key=<single line>, for Kafka Connect's
#                              FileConfigProvider:
#                              "snowflake.private.key":
#                                "${file:/opt/secrets/snowflake.properties:private.key}"
# And next to this script:
#   snowflake_setup_rendered.sql  snowflake_setup.sql with the public key filled in
#
# Re-running reuses an existing key. Delete the secrets folder to rotate.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS_DIR="${1:-$SCRIPT_DIR/secrets}"
TEMPLATE="$SCRIPT_DIR/snowflake_setup.sql"
RENDERED="$SCRIPT_DIR/snowflake_setup_rendered.sql"
PRIV="$SECRETS_DIR/sf_kafka_key.p8"
PUB="$SECRETS_DIR/sf_kafka_key.pub"
PROPS="$SECRETS_DIR/snowflake.properties"

command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }
[ -f "$TEMPLATE" ] || { echo "Missing $TEMPLATE (keep it next to this script)" >&2; exit 1; }

umask 077
mkdir -p "$SECRETS_DIR"

if [ -f "$PRIV" ]; then
  echo "Reusing existing private key: $PRIV"
else
  openssl genrsa 2048 2>/dev/null \
    | openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt -out "$PRIV"
  echo "Created private key: $PRIV"
fi
openssl rsa -in "$PRIV" -pubout -out "$PUB" 2>/dev/null

# Header/footer and line breaks removed, as Snowflake and the connector expect.
PUB_ONE_LINE="$(grep -v -- '-----' "$PUB" | tr -d '\r\n')"
PRIV_ONE_LINE="$(grep -v -- '-----' "$PRIV" | tr -d '\r\n')"

printf 'private.key=%s\n' "$PRIV_ONE_LINE" > "$PROPS"

sed "s|<<RSA_PUBLIC_KEY>>|$PUB_ONE_LINE|" "$TEMPLATE" > "$RENDERED"
chmod 644 "$RENDERED"

FINGERPRINT="SHA256:$(openssl rsa -pubin -in "$PUB" -outform DER 2>/dev/null \
  | openssl dgst -sha256 -binary | openssl enc -base64)"

cat <<EOF

Done.
  Snowflake SQL to run : $RENDERED
  Connector secret     : $PROPS  (mount into Kafka Connect, e.g. /opt/secrets/)
  Key fingerprint      : $FINGERPRINT
                         (must equal RSA_PUBLIC_KEY_FP in DESC USER KAFKA_CONNECTOR_USER)

Never commit the secrets folder to git.
EOF
