# Kafka Connect worker with:
#   - Debezium (Oracle source connector) from the official image
#   - Oracle JDBC driver (added only if the image doesn't already ship one)
#   - Snowflake Connector for Kafka v4 + Bouncy Castle FIPS libraries it needs
ARG DEBEZIUM_VERSION=3.4
FROM quay.io/debezium/connect:${DEBEZIUM_VERSION}

ARG SNOWFLAKE_CONNECTOR_VERSION=4.2.2
ARG BC_FIPS_VERSION=2.1.0
ARG BCPKIX_FIPS_VERSION=2.1.8
ARG OJDBC_VERSION=23.9.0.25.07
ARG MAVEN=https://repo1.maven.org/maven2

RUN set -eux; \
    SF_DIR=/kafka/connect/snowflake-kafka-connector; \
    mkdir -p "$SF_DIR"; \
    curl -fsSL -o "$SF_DIR/snowflake-kafka-connector-${SNOWFLAKE_CONNECTOR_VERSION}.jar" \
      "$MAVEN/com/snowflake/snowflake-kafka-connector/${SNOWFLAKE_CONNECTOR_VERSION}/snowflake-kafka-connector-${SNOWFLAKE_CONNECTOR_VERSION}.jar"; \
    curl -fsSL -o "$SF_DIR/bc-fips-${BC_FIPS_VERSION}.jar" \
      "$MAVEN/org/bouncycastle/bc-fips/${BC_FIPS_VERSION}/bc-fips-${BC_FIPS_VERSION}.jar"; \
    curl -fsSL -o "$SF_DIR/bcpkix-fips-${BCPKIX_FIPS_VERSION}.jar" \
      "$MAVEN/org/bouncycastle/bcpkix-fips/${BCPKIX_FIPS_VERSION}/bcpkix-fips-${BCPKIX_FIPS_VERSION}.jar"; \
    ORA_DIR=/kafka/connect/debezium-connector-oracle; \
    if ls "$ORA_DIR"/ojdbc*.jar >/dev/null 2>&1; then \
      echo "Oracle JDBC driver already present in $ORA_DIR"; \
    else \
      curl -fsSL -o "$ORA_DIR/ojdbc11-${OJDBC_VERSION}.jar" \
        "$MAVEN/com/oracle/database/jdbc/ojdbc11/${OJDBC_VERSION}/ojdbc11-${OJDBC_VERSION}.jar"; \
    fi; \
    ls -l "$SF_DIR" "$ORA_DIR" | grep -E 'snowflake|bc|ojdbc'
