/* =====================================================================
   Read-only Snowflake access for the customer portal (portal/app.py)

   SAP_PORTAL_ROLE  can only SELECT the Gold sales tables and use the warehouse
   SAP_PORTAL_USER  service user, key-pair login (no password)

   Before running: create the key pair on your PC (Git Bash, project folder):
     openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out snowflake/secrets/portal_key.p8 -nocrypt
     openssl rsa -in snowflake/secrets/portal_key.p8 -pubout -out snowflake/secrets/portal_key.pub
     grep -v -- '-----' snowflake/secrets/portal_key.pub | tr -d '\r\n'; echo
   Paste the printed one-line public key into RSA_PUBLIC_KEY below.
   ===================================================================== */

USE ROLE USERADMIN;
CREATE ROLE IF NOT EXISTS SAP_PORTAL_ROLE
  COMMENT = 'Customer portal: read-only on SAP_GOLD.SALES';
CREATE USER IF NOT EXISTS SAP_PORTAL_USER
  TYPE = SERVICE
  DEFAULT_ROLE = SAP_PORTAL_ROLE
  DEFAULT_WAREHOUSE = SAP_TRANSFORM_WH
  COMMENT = 'portal/app.py';
ALTER USER SAP_PORTAL_USER SET RSA_PUBLIC_KEY = '<paste one-line public key here>';

USE ROLE SECURITYADMIN;
GRANT ROLE SAP_PORTAL_ROLE TO USER SAP_PORTAL_USER;
GRANT ROLE SAP_PORTAL_ROLE TO ROLE SYSADMIN;

GRANT USAGE ON WAREHOUSE SAP_TRANSFORM_WH TO ROLE SAP_PORTAL_ROLE;
GRANT USAGE ON DATABASE SAP_GOLD          TO ROLE SAP_PORTAL_ROLE;
GRANT USAGE ON SCHEMA   SAP_GOLD.SALES    TO ROLE SAP_PORTAL_ROLE;
GRANT SELECT ON ALL    DYNAMIC TABLES IN SCHEMA SAP_GOLD.SALES TO ROLE SAP_PORTAL_ROLE;
GRANT SELECT ON FUTURE DYNAMIC TABLES IN SCHEMA SAP_GOLD.SALES TO ROLE SAP_PORTAL_ROLE;
GRANT SELECT ON ALL    VIEWS          IN SCHEMA SAP_GOLD.SALES TO ROLE SAP_PORTAL_ROLE;

-- Check: fingerprint must match `openssl rsa -pubin -in snowflake/secrets/portal_key.pub -outform DER | openssl dgst -sha256 -binary | openssl enc -base64`
DESC USER SAP_PORTAL_USER;
SHOW GRANTS TO ROLE SAP_PORTAL_ROLE;

-- Optional: a small dedicated warehouse so portal queries never wait behind the MERGE tasks
-- USE ROLE SYSADMIN;
-- CREATE WAREHOUSE IF NOT EXISTS SAP_PORTAL_WH WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE;
-- GRANT USAGE ON WAREHOUSE SAP_PORTAL_WH TO ROLE SAP_PORTAL_ROLE;   -- then SNOWFLAKE_WAREHOUSE=SAP_PORTAL_WH in portal/.env

/* ---------------------------------------------------------------------
   AI assistant in the portal: let SAP_PORTAL_ROLE use the Cortex Agent
   (run after snowflake/05_sales_agent.sql has created the agent)
   --------------------------------------------------------------------- */
USE ROLE ACCOUNTADMIN;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_AGENT_USER                 TO ROLE SAP_PORTAL_ROLE;
GRANT USAGE  ON AGENT         SAP_GOLD.SALES.SAP_SALES_AGENT     TO ROLE SAP_PORTAL_ROLE;
GRANT SELECT ON SEMANTIC VIEW SAP_GOLD.SALES.SV_SAP_SALES        TO ROLE SAP_PORTAL_ROLE;
SHOW GRANTS TO ROLE SAP_PORTAL_ROLE;
