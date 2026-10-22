/* =====================================================================
   Debezium LogMiner prerequisites for Oracle Database Free (CDB FREE,
   PDB FREEPDB1). Run as SYSDBA in CDB$ROOT, after ARCHIVELOG mode is on
   (scripts/01_oracle_setup.sh does both). Safe to re-run.
   ===================================================================== */
WHENEVER SQLERROR EXIT FAILURE
SET SERVEROUTPUT ON FEEDBACK OFF

-- Minimal database-level supplemental logging (table-level ALL COLUMNS
-- logging is added by s4_sd_oracle_ddl.sql for each SAP table).
DECLARE
  v_min VARCHAR2(10);
BEGIN
  SELECT supplemental_log_data_min INTO v_min FROM v$database;
  IF v_min = 'NO' THEN
    EXECUTE IMMEDIATE 'ALTER DATABASE ADD SUPPLEMENTAL LOG DATA';
    DBMS_OUTPUT.PUT_LINE('Supplemental logging enabled');
  ELSE
    DBMS_OUTPUT.PUT_LINE('Supplemental logging already enabled');
  END IF;
END;
/

-- LogMiner tablespace must exist in the root AND the PDB, because the
-- common user's default tablespace has to exist in every container.
DECLARE
  PROCEDURE run_ignoring(p_sql VARCHAR2, p_ignore NUMBER) IS
  BEGIN
    EXECUTE IMMEDIATE p_sql;
  EXCEPTION WHEN OTHERS THEN
    IF SQLCODE != p_ignore THEN RAISE; END IF;
  END;
BEGIN
  run_ignoring('CREATE TABLESPACE logminer_tbs DATAFILE ''/opt/oracle/oradata/FREE/logminer_tbs.dbf''
                SIZE 25M REUSE AUTOEXTEND ON MAXSIZE UNLIMITED', -1543);  -- ORA-01543: already exists
END;
/

ALTER SESSION SET CONTAINER = FREEPDB1;

DECLARE
  PROCEDURE run_ignoring(p_sql VARCHAR2, p_ignore NUMBER) IS
  BEGIN
    EXECUTE IMMEDIATE p_sql;
  EXCEPTION WHEN OTHERS THEN
    IF SQLCODE != p_ignore THEN RAISE; END IF;
  END;
BEGIN
  run_ignoring('CREATE TABLESPACE logminer_tbs DATAFILE ''/opt/oracle/oradata/FREE/FREEPDB1/logminer_tbs.dbf''
                SIZE 25M REUSE AUTOEXTEND ON MAXSIZE UNLIMITED', -1543);
END;
/

-- The SAP schema owner needs space for the SD tables.
ALTER USER SAPSD QUOTA UNLIMITED ON USERS;

ALTER SESSION SET CONTAINER = CDB$ROOT;

-- Common user Debezium connects as.
DECLARE
  v_cnt NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_cnt FROM dba_users WHERE username = 'C##DBZUSER';
  IF v_cnt = 0 THEN
    EXECUTE IMMEDIATE 'CREATE USER c##dbzuser IDENTIFIED BY dbz
                       DEFAULT TABLESPACE logminer_tbs
                       QUOTA UNLIMITED ON logminer_tbs
                       CONTAINER = ALL';
    DBMS_OUTPUT.PUT_LINE('Created c##dbzuser');
  END IF;
END;
/

GRANT CREATE SESSION          TO c##dbzuser CONTAINER = ALL;
GRANT SET CONTAINER           TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$DATABASE   TO c##dbzuser CONTAINER = ALL;
GRANT FLASHBACK ANY TABLE     TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ANY TABLE        TO c##dbzuser CONTAINER = ALL;
GRANT SELECT_CATALOG_ROLE     TO c##dbzuser CONTAINER = ALL;
GRANT EXECUTE_CATALOG_ROLE    TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ANY TRANSACTION  TO c##dbzuser CONTAINER = ALL;
GRANT LOGMINING               TO c##dbzuser CONTAINER = ALL;
GRANT CREATE TABLE            TO c##dbzuser CONTAINER = ALL;
GRANT LOCK ANY TABLE          TO c##dbzuser CONTAINER = ALL;
GRANT CREATE SEQUENCE         TO c##dbzuser CONTAINER = ALL;
GRANT EXECUTE ON DBMS_LOGMNR   TO c##dbzuser CONTAINER = ALL;
GRANT EXECUTE ON DBMS_LOGMNR_D TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$LOG                 TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$LOG_HISTORY         TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$LOGMNR_LOGS         TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$LOGMNR_CONTENTS     TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$LOGMNR_PARAMETERS   TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$LOGFILE             TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$ARCHIVED_LOG        TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$ARCHIVE_DEST_STATUS TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$TRANSACTION         TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$MYSTAT              TO c##dbzuser CONTAINER = ALL;
GRANT SELECT ON V_$STATNAME            TO c##dbzuser CONTAINER = ALL;

PROMPT Debezium user ready
EXIT
