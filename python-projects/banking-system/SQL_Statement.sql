SELECT value FROM v$parameter WHERE name='service_names';

SELECT username, account_status 
FROM dba_users 
WHERE username = 'BANK';

CREATE USER bank IDENTIFIED BY bank;

ALTER SESSION SET CONTAINER = XEPDB1;

GRANT CREATE SESSION TO BANK;

SELECT * FROM all_tables
where owner = 'BANK';

GRANT CREATE SESSION TO BANK;
GRANT CREATE TABLE TO BANK;
GRANT CREATE VIEW TO BANK;
GRANT CREATE SEQUENCE TO BANK;

ALTER USER BANK 
DEFAULT TABLESPACE users 
QUOTA UNLIMITED ON users;


SELECT * FROM bank.customers;
SELECT * FROM bank.address;
SELECT * FROM bank.accounts;
SELECT * FROM bank.fd;
SELECT * FROM bank.loans;
SELECT * FROM bank.transactions;
SELECT * FROM bank.admin;
SELECT * FROM bank.accounts_fd;
SELECT * FROM bank.accounts_loans