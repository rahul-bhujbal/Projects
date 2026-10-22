/* =====================================================================
   Snowflake setup for the Snowflake Connector for Kafka v4
   Oracle (SAP SD) -> Debezium -> Kafka -> Snowflake VARIANT landing tables

   Creates:
     Warehouse  SAP_TRANSFORM_WH      (for MERGE / views / tasks only;
                                       the connector itself needs no warehouse)
     Databases  SAP_RAW.SD            (connector lands RECORD_CONTENT /
                                       RECORD_METADATA VARIANT tables here)
                SAP_CORE.SD           (typed current-state tables you build)
     Roles      KAFKA_CONNECTOR_ROLE  (writes raw tables, nothing else)
                SAP_TRANSFORM_ROLE    (reads raw, builds core)
     User       KAFKA_CONNECTOR_USER  (service user, key-pair auth only)

   How to run
     1. Run generate_snowflake_keys.sh. It creates the key pair and writes
        snowflake_setup_rendered.sql with your public key filled in.
     2. Run snowflake_setup_rendered.sql in a Snowsight worksheet, as a
        user that has ACCOUNTADMIN (or SYSADMIN + USERADMIN + SECURITYADMIN).
     3. Compare RSA_PUBLIC_KEY_FP from DESC USER (section 6) with the
        fingerprint the key script printed.

   Safe to re-run: every CREATE uses IF NOT EXISTS, and the public key
   is (re)applied with ALTER USER.
   ===================================================================== */

/* ---------------------------------------------------------------------
   1. Warehouse, databases, schemas  (SYSADMIN)
   --------------------------------------------------------------------- */
USE ROLE SYSADMIN;

CREATE WAREHOUSE IF NOT EXISTS SAP_TRANSFORM_WH
  WAREHOUSE_SIZE      = 'XSMALL'
  AUTO_SUSPEND        = 60
  AUTO_RESUME         = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'MERGE tasks and queries on SAP CDC data. Not used by the Kafka connector.';

-- Time Travel: 1 day is the Standard-edition maximum; raise on Enterprise
-- so you can recover from a bad transformation.
CREATE DATABASE IF NOT EXISTS SAP_RAW
  DATA_RETENTION_TIME_IN_DAYS = 1
  COMMENT = 'Raw CDC events from Kafka, one VARIANT table per Oracle table';
CREATE SCHEMA IF NOT EXISTS SAP_RAW.SD
  COMMENT = 'SAP Sales & Distribution CDC landing tables (written by Kafka connector)';

CREATE DATABASE IF NOT EXISTS SAP_CORE
  DATA_RETENTION_TIME_IN_DAYS = 1
  COMMENT = 'Typed, current-state SAP tables built from SAP_RAW';
CREATE SCHEMA IF NOT EXISTS SAP_CORE.SD
  COMMENT = 'SAP Sales & Distribution current-state tables';

/* ---------------------------------------------------------------------
   2. Roles and the connector's service user  (USERADMIN)
   --------------------------------------------------------------------- */
USE ROLE USERADMIN;

CREATE ROLE IF NOT EXISTS KAFKA_CONNECTOR_ROLE
  COMMENT = 'Used only by the Snowflake Kafka connector to write SAP_RAW.SD';
CREATE ROLE IF NOT EXISTS SAP_TRANSFORM_ROLE
  COMMENT = 'Reads SAP_RAW, builds SAP_CORE (streams, tasks, MERGE, views)';

CREATE USER IF NOT EXISTS KAFKA_CONNECTOR_USER
  TYPE         = SERVICE          -- no password, no interactive login
  DEFAULT_ROLE = KAFKA_CONNECTOR_ROLE
  COMMENT      = 'Kafka Connect: Snowflake Connector for Kafka v4';

-- Applied separately so re-running the script rotates/sets the key.
ALTER USER KAFKA_CONNECTOR_USER SET
  RSA_PUBLIC_KEY = '<<RSA_PUBLIC_KEY>>';

/* ---------------------------------------------------------------------
   3. Role hierarchy and connector privileges  (SECURITYADMIN)
      Privileges are granted directly to KAFKA_CONNECTOR_ROLE: the
      connector does not pick them up through inherited roles.
   --------------------------------------------------------------------- */
USE ROLE SECURITYADMIN;

GRANT ROLE KAFKA_CONNECTOR_ROLE TO USER KAFKA_CONNECTOR_USER;

-- Let SYSADMIN manage what these roles create (best practice).
GRANT ROLE KAFKA_CONNECTOR_ROLE TO ROLE SYSADMIN;
GRANT ROLE SAP_TRANSFORM_ROLE   TO ROLE SYSADMIN;

-- Connector: land data in SAP_RAW.SD and nowhere else.
GRANT USAGE        ON DATABASE SAP_RAW    TO ROLE KAFKA_CONNECTOR_ROLE;
GRANT USAGE        ON SCHEMA   SAP_RAW.SD TO ROLE KAFKA_CONNECTOR_ROLE;
GRANT CREATE TABLE ON SCHEMA   SAP_RAW.SD TO ROLE KAFKA_CONNECTOR_ROLE;  -- auto-created VARIANT tables
GRANT CREATE PIPE  ON SCHEMA   SAP_RAW.SD TO ROLE KAFKA_CONNECTOR_ROLE;  -- default {TABLE}-STREAMING pipes
GRANT CREATE VIEW  ON SCHEMA   SAP_RAW.SD TO ROLE KAFKA_CONNECTOR_ROLE;  -- recommended for error tables

/* ---------------------------------------------------------------------
   4. Transformation role privileges  (SECURITYADMIN)
   --------------------------------------------------------------------- */
GRANT USAGE ON WAREHOUSE SAP_TRANSFORM_WH TO ROLE SAP_TRANSFORM_ROLE;

-- Read every raw table, including ones the connector creates later.
GRANT USAGE  ON DATABASE SAP_RAW                     TO ROLE SAP_TRANSFORM_ROLE;
GRANT USAGE  ON SCHEMA   SAP_RAW.SD                  TO ROLE SAP_TRANSFORM_ROLE;
GRANT SELECT ON ALL    TABLES IN SCHEMA SAP_RAW.SD   TO ROLE SAP_TRANSFORM_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA SAP_RAW.SD   TO ROLE SAP_TRANSFORM_ROLE;

-- Build current-state objects in SAP_CORE.SD.
GRANT USAGE                ON DATABASE SAP_CORE    TO ROLE SAP_TRANSFORM_ROLE;
GRANT USAGE                ON SCHEMA   SAP_CORE.SD TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE TABLE         ON SCHEMA   SAP_CORE.SD TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE VIEW          ON SCHEMA   SAP_CORE.SD TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE STREAM        ON SCHEMA   SAP_CORE.SD TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE TASK          ON SCHEMA   SAP_CORE.SD TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE DYNAMIC TABLE ON SCHEMA   SAP_CORE.SD TO ROLE SAP_TRANSFORM_ROLE;

-- Give yourself the transform role (replace with your Snowflake login name).
-- GRANT ROLE SAP_TRANSFORM_ROLE TO USER <YOUR_SNOWFLAKE_USER>;

-- Running scheduled tasks is an account-level privilege.
USE ROLE ACCOUNTADMIN;
GRANT EXECUTE TASK ON ACCOUNT TO ROLE SAP_TRANSFORM_ROLE;

/* ---------------------------------------------------------------------
   5. Optional: only allow the connector to log in from your Kafka
      Connect host(s). Replace the IP and uncomment.
   --------------------------------------------------------------------- */
-- USE ROLE ACCOUNTADMIN;
-- CREATE NETWORK RULE IF NOT EXISTS SAP_RAW.SD.KAFKA_CONNECT_IPS
--   TYPE = IPV4 MODE = INGRESS VALUE_LIST = ('203.0.113.10/32');
-- CREATE NETWORK POLICY IF NOT EXISTS KAFKA_CONNECTOR_POLICY
--   ALLOWED_NETWORK_RULE_LIST = ('SAP_RAW.SD.KAFKA_CONNECT_IPS');
-- ALTER USER KAFKA_CONNECTOR_USER SET NETWORK_POLICY = KAFKA_CONNECTOR_POLICY;

/* ---------------------------------------------------------------------
   6. Verify, and collect the values for the connector config
   --------------------------------------------------------------------- */
USE ROLE SECURITYADMIN;

-- RSA_PUBLIC_KEY_FP must match the fingerprint printed by the key script.
DESC USER KAFKA_CONNECTOR_USER;

SHOW GRANTS TO ROLE KAFKA_CONNECTOR_ROLE;
SHOW GRANTS TO ROLE SAP_TRANSFORM_ROLE;
SHOW FUTURE GRANTS IN SCHEMA SAP_RAW.SD;

-- Value for "snowflake.url.name" in the connector config.
SELECT 'https://' || LOWER(CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME())
       || '.snowflakecomputing.com'                       AS snowflake_url_name,
       'KAFKA_CONNECTOR_USER'                             AS snowflake_user_name,
       'KAFKA_CONNECTOR_ROLE'                             AS snowflake_role_name,
       'SAP_RAW'                                          AS snowflake_database_name,
       'SD'                                               AS snowflake_schema_name,
       CURRENT_REGION()                                   AS region_run_kafka_connect_nearby;

/* ---------------------------------------------------------------------
   7. After the connector has created the raw tables
      The connector's role owns them, so change tracking (needed for
      streams) must be switched on by the owner. SYSADMIN inherits
      KAFKA_CONNECTOR_ROLE, so it can do this. Run once per new table.
   --------------------------------------------------------------------- */
-- USE ROLE SYSADMIN;
-- SHOW TABLES IN SCHEMA SAP_RAW.SD;
-- ALTER TABLE SAP_RAW.SD.VBAK_RAW SET CHANGE_TRACKING = TRUE;
-- ALTER TABLE SAP_RAW.SD.VBAP_RAW SET CHANGE_TRACKING = TRUE;

/* ---------------------------------------------------------------------
   8. Teardown (removes everything above). Uncomment to use.
   --------------------------------------------------------------------- */
-- USE ROLE ACCOUNTADMIN;
-- DROP USER      IF EXISTS KAFKA_CONNECTOR_USER;
-- DROP DATABASE  IF EXISTS SAP_RAW;
-- DROP DATABASE  IF EXISTS SAP_CORE;
-- DROP WAREHOUSE IF EXISTS SAP_TRANSFORM_WH;
-- DROP ROLE      IF EXISTS KAFKA_CONNECTOR_ROLE;
-- DROP ROLE      IF EXISTS SAP_TRANSFORM_ROLE;
