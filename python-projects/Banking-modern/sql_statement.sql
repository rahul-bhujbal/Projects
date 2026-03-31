CREATE USER bank_modern IDENTIFIED BY bank;

ALTER SESSION SET CONTAINER = XEPDB1;

GRANT CREATE SESSION TO bank_modern;

SELECT * FROM all_tables
where owner = 'BANK';

GRANT CREATE SESSION TO bank_modern;
GRANT CREATE TABLE TO bank_modern;
GRANT CREATE VIEW TO bank_modern;
GRANT CREATE SEQUENCE TO bank_modern;

-- Banking OLTP initial schema (simplified)

DROP TABLE bank_modern.customers;
CREATE TABLE bank_modern.customers (
    id NUMBER GENERATED AS IDENTITY PRIMARY KEY,
    first_name VARCHAR2(100) NOT NULL,
    last_name VARCHAR2(100) NOT NULL,
    email VARCHAR2(255) UNIQUE NOT NULL,
    created_at DATE
);


CREATE TABLE bank_modern.accounts (
    id NUMBER GENERATED AS IDENTITY PRIMARY KEY,
    customer_id NUMBER NOT NULL,
    account_type VARCHAR2(50) NOT NULL,
    balance NUMBER(18,2) DEFAULT 0 CHECK (balance >= 0),
    currency CHAR(3) DEFAULT 'USD',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,

    CONSTRAINT fk_customer
    FOREIGN KEY (customer_id)
    REFERENCES bank_modern.customers(id)
    ON DELETE CASCADE
);


CREATE TABLE bank_modern.transactions (
    id NUMBER GENERATED AS IDENTITY PRIMARY KEY,
    account_id NUMBER NOT NULL,
    txn_type VARCHAR2(50) NOT NULL,
    amount NUMBER(18,2) NOT NULL CHECK (amount > 0),
    related_account_id NUMBER,
    status VARCHAR2(20) DEFAULT 'COMPLETED' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,

    CONSTRAINT fk_txn_account
    FOREIGN KEY (account_id)
    REFERENCES bank_modern.accounts(id)
    ON DELETE CASCADE
);

SHOW CON_NAME;

-- Simple indexed columns for performance in queries
CREATE INDEX  idx_transactions_account_created ON bank_modern.transactions(account_id, created_at);



SELECT * FROM bank_modern.customers;
SELECT * FROM bank_modern.accounts;
SELECT * FROM bank_modern.transactions;

truncate table bank_modern.customers;
truncate table bank_modern.accounts;
truncate table bank_modern.transactions;


ALTER SESSION SET CONTAINER = XEPDB1;

ALTER USER bank_modern QUOTA UNLIMITED ON USERS;

ALTER USER BANK DEFAULT TABLESPACE USERS;

