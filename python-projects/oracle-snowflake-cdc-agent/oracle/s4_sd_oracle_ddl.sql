/* =====================================================================
   SAP S/4HANA Sales & Distribution (SD) - core tables for Oracle
   Target : Oracle Database Free, PDB FREEPDB1
   Schema : SAPSD
   ---------------------------------------------------------------------
   Notes
   - Table and field names follow SAP's data dictionary (DDIC).
   - Each table carries the business-relevant subset of fields, not
     every SAP field (real VBAK has 200+ columns).
   - S/4HANA specifics reflected here:
       * VBUK / VBUP are gone: header/item statuses live in
         VBAK/VBAP, LIKP/LIPS, VBRK/VBRP.
       * KONV is replaced by PRCD_ELEMENTS for pricing conditions.
       * VBFA has a GUID key (RUUID); document categories are CHAR(4).
       * MATNR is 40 characters.
       * Customers are Business Partners (BUT000) linked to KNA1
         through CVI_CUST_LINK.
   - Type mapping: CHAR/NUMC -> VARCHAR2 (keep leading zeros),
     DATS -> DATE, TIMS -> VARCHAR2(6) 'HHMMSS',
     CURR/DEC -> NUMBER(p,s), QUAN -> NUMBER(p,3).
   - Like SAP, no foreign keys are enforced; indexes are added on the
     common join paths instead.
   ===================================================================== */

-- ---------------------------------------------------------------------
-- 0. Schema (run as SYSTEM in FREEPDB1)
-- ---------------------------------------------------------------------
-- ALTER SESSION SET CONTAINER = FREEPDB1;
-- CREATE USER sapsd IDENTIFIED BY sapsd QUOTA UNLIMITED ON users;
-- GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE, CREATE VIEW TO sapsd;
-- ALTER SESSION SET CURRENT_SCHEMA = sapsd;

/* =====================================================================
   1. ORGANIZATIONAL STRUCTURE / CUSTOMIZING
   ===================================================================== */

-- Company codes
CREATE TABLE t001 (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  bukrs   VARCHAR2(4)  NOT NULL,          -- Company code
  butxt   VARCHAR2(25),                   -- Name
  ort01   VARCHAR2(25),                   -- City
  land1   VARCHAR2(3),                    -- Country
  waers   VARCHAR2(5),                    -- Currency
  spras   VARCHAR2(1),                    -- Language
  ktopl   VARCHAR2(4),                    -- Chart of accounts
  CONSTRAINT pk_t001 PRIMARY KEY (mandt, bukrs)
);

-- Plants
CREATE TABLE t001w (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  werks   VARCHAR2(4)  NOT NULL,          -- Plant
  name1   VARCHAR2(30),
  bwkey   VARCHAR2(4),                    -- Valuation area
  vkorg   VARCHAR2(4),                    -- Sales org for intercompany
  vtweg   VARCHAR2(2),
  spart   VARCHAR2(2),
  land1   VARCHAR2(3),
  regio   VARCHAR2(3),                    -- Region / state
  ort01   VARCHAR2(25),
  pstlz   VARCHAR2(10),
  CONSTRAINT pk_t001w PRIMARY KEY (mandt, werks)
);

-- Sales organizations
CREATE TABLE tvko (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vkorg   VARCHAR2(4)  NOT NULL,          -- Sales organization
  waers   VARCHAR2(5),                    -- Statistics currency
  bukrs   VARCHAR2(4),                    -- Company code
  kunnr   VARCHAR2(10),                   -- Intercompany customer
  CONSTRAINT pk_tvko PRIMARY KEY (mandt, vkorg)
);

-- Distribution channels
CREATE TABLE tvtw (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vtweg   VARCHAR2(2)  NOT NULL,
  vtext   VARCHAR2(20),                   -- (text normally in TVTWT)
  CONSTRAINT pk_tvtw PRIMARY KEY (mandt, vtweg)
);

-- Divisions
CREATE TABLE tspa (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  spart   VARCHAR2(2)  NOT NULL,
  vtext   VARCHAR2(20),                   -- (text normally in TSPAT)
  CONSTRAINT pk_tspa PRIMARY KEY (mandt, spart)
);

-- Sales areas (valid combinations)
CREATE TABLE tvta (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vkorg   VARCHAR2(4)  NOT NULL,
  vtweg   VARCHAR2(2)  NOT NULL,
  spart   VARCHAR2(2)  NOT NULL,
  CONSTRAINT pk_tvta PRIMARY KEY (mandt, vkorg, vtweg, spart)
);

-- Sales document types
CREATE TABLE tvak (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  auart   VARCHAR2(4)  NOT NULL,          -- OR, RE, CR, DR ...
  vbtyp   VARCHAR2(4),                    -- Document category (S/4: CHAR4)
  numki   VARCHAR2(2),                    -- Internal number range
  bezei   VARCHAR2(20),
  CONSTRAINT pk_tvak PRIMARY KEY (mandt, auart)
);

-- Delivery types
CREATE TABLE tvlk (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  lfart   VARCHAR2(4)  NOT NULL,          -- LF, LR ...
  vbtyp   VARCHAR2(4),
  bezei   VARCHAR2(20),
  CONSTRAINT pk_tvlk PRIMARY KEY (mandt, lfart)
);

-- Billing types
CREATE TABLE tvfk (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  fkart   VARCHAR2(4)  NOT NULL,          -- F2, S1, G2, RE ...
  vbtyp   VARCHAR2(4),
  fktyp   VARCHAR2(1),
  bezei   VARCHAR2(20),
  CONSTRAINT pk_tvfk PRIMARY KEY (mandt, fkart)
);

/* =====================================================================
   2. BUSINESS PARTNER / CUSTOMER MASTER
   ===================================================================== */

-- Business partner (S/4 leading object for customers)
CREATE TABLE but000 (
  client      VARCHAR2(3)  DEFAULT '100' NOT NULL,
  partner     VARCHAR2(10) NOT NULL,      -- BP number
  type        VARCHAR2(1),                -- 1 person, 2 organization
  bu_group    VARCHAR2(4),                -- BP grouping
  partner_guid RAW(16)     DEFAULT SYS_GUID() NOT NULL,
  name_org1   VARCHAR2(40),
  name_org2   VARCHAR2(40),
  name_first  VARCHAR2(40),
  name_last   VARCHAR2(40),
  crusr       VARCHAR2(12),
  crdat       DATE,
  crtim       VARCHAR2(6),
  chusr       VARCHAR2(12),
  chdat       DATE,
  chtim       VARCHAR2(6),
  xdele       VARCHAR2(1),                -- Archiving flag
  xblck       VARCHAR2(1),                -- Central block
  CONSTRAINT pk_but000 PRIMARY KEY (client, partner)
);
CREATE UNIQUE INDEX ux_but000_guid ON but000 (client, partner_guid);

-- BP <-> customer link (Customer/Vendor Integration)
CREATE TABLE cvi_cust_link (
  client        VARCHAR2(3)  DEFAULT '100' NOT NULL,
  partner_guid  RAW(16)      NOT NULL,
  customer      VARCHAR2(10) NOT NULL,
  CONSTRAINT pk_cvi_cust_link PRIMARY KEY (client, partner_guid)
);
CREATE UNIQUE INDEX ux_cvi_cust_link_kunnr ON cvi_cust_link (client, customer);

-- Customer general data
CREATE TABLE kna1 (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  kunnr   VARCHAR2(10) NOT NULL,          -- Customer number
  land1   VARCHAR2(3),
  name1   VARCHAR2(35),
  name2   VARCHAR2(35),
  ort01   VARCHAR2(35),                   -- City
  pstlz   VARCHAR2(10),                   -- Postal code
  regio   VARCHAR2(3),                    -- Region / state
  stras   VARCHAR2(35),                   -- Street
  telf1   VARCHAR2(16),
  adrnr   VARCHAR2(10),                   -- Address number
  ktokd   VARCHAR2(4),                    -- Account group
  stcd3   VARCHAR2(18),                   -- Tax number 3 (e.g. GSTIN)
  brsch   VARCHAR2(4),                    -- Industry
  erdat   DATE,
  ernam   VARCHAR2(12),
  aufsd   VARCHAR2(2),                    -- Central order block
  lifsd   VARCHAR2(2),                    -- Central delivery block
  faksd   VARCHAR2(2),                    -- Central billing block
  loevm   VARCHAR2(1),                    -- Deletion flag
  CONSTRAINT pk_kna1 PRIMARY KEY (mandt, kunnr)
);

-- Customer company-code data
CREATE TABLE knb1 (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  kunnr   VARCHAR2(10) NOT NULL,
  bukrs   VARCHAR2(4)  NOT NULL,
  akont   VARCHAR2(10),                   -- Reconciliation account
  zterm   VARCHAR2(4),                    -- Payment terms
  zwels   VARCHAR2(10),                   -- Payment methods
  erdat   DATE,
  ernam   VARCHAR2(12),
  loevm   VARCHAR2(1),
  CONSTRAINT pk_knb1 PRIMARY KEY (mandt, kunnr, bukrs)
);

-- Customer sales-area data
CREATE TABLE knvv (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  kunnr   VARCHAR2(10) NOT NULL,
  vkorg   VARCHAR2(4)  NOT NULL,
  vtweg   VARCHAR2(2)  NOT NULL,
  spart   VARCHAR2(2)  NOT NULL,
  kdgrp   VARCHAR2(2),                    -- Customer group
  bzirk   VARCHAR2(6),                    -- Sales district
  vkbur   VARCHAR2(4),                    -- Sales office
  vkgrp   VARCHAR2(3),                    -- Sales group
  waers   VARCHAR2(5),
  kalks   VARCHAR2(1),                    -- Pricing procedure indicator
  konda   VARCHAR2(2),                    -- Price group
  pltyp   VARCHAR2(2),                    -- Price list type
  vsbed   VARCHAR2(2),                    -- Shipping conditions
  vwerk   VARCHAR2(4),                    -- Delivering plant
  inco1   VARCHAR2(3),                    -- Incoterms
  inco2   VARCHAR2(28),
  zterm   VARCHAR2(4),
  ktgrd   VARCHAR2(2),                    -- Account assignment group
  aufsd   VARCHAR2(2),
  lifsd   VARCHAR2(2),
  faksd   VARCHAR2(2),
  erdat   DATE,
  ernam   VARCHAR2(12),
  loevm   VARCHAR2(1),
  CONSTRAINT pk_knvv PRIMARY KEY (mandt, kunnr, vkorg, vtweg, spart)
);

-- Customer partner functions (sold-to, ship-to, bill-to, payer)
CREATE TABLE knvp (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  kunnr   VARCHAR2(10) NOT NULL,
  vkorg   VARCHAR2(4)  NOT NULL,
  vtweg   VARCHAR2(2)  NOT NULL,
  spart   VARCHAR2(2)  NOT NULL,
  parvw   VARCHAR2(2)  NOT NULL,          -- AG sold-to, WE ship-to, RE bill-to, RG payer
  parza   VARCHAR2(3)  NOT NULL,          -- Partner counter
  kunn2   VARCHAR2(10),                   -- Partner customer
  lifnr   VARCHAR2(10),
  pernr   VARCHAR2(8),
  defpa   VARCHAR2(1),                    -- Default partner
  CONSTRAINT pk_knvp PRIMARY KEY (mandt, kunnr, vkorg, vtweg, spart, parvw, parza)
);

/* =====================================================================
   3. MATERIAL MASTER
   ===================================================================== */

-- Material general data
CREATE TABLE mara (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  matnr   VARCHAR2(40) NOT NULL,          -- S/4: 40 characters
  ersda   DATE,
  ernam   VARCHAR2(12),
  laeda   DATE,
  aenam   VARCHAR2(12),
  lvorm   VARCHAR2(1),                    -- Deletion flag
  mtart   VARCHAR2(4),                    -- Material type (FERT, HAWA ...)
  mbrsh   VARCHAR2(1),                    -- Industry sector
  matkl   VARCHAR2(9),                    -- Material group
  meins   VARCHAR2(3),                    -- Base unit
  brgew   NUMBER(13,3),                   -- Gross weight
  ntgew   NUMBER(13,3),                   -- Net weight
  gewei   VARCHAR2(3),                    -- Weight unit
  volum   NUMBER(13,3),
  voleh   VARCHAR2(3),
  spart   VARCHAR2(2),                    -- Division
  prdha   VARCHAR2(18),                   -- Product hierarchy
  ean11   VARCHAR2(18),                   -- EAN/UPC
  CONSTRAINT pk_mara PRIMARY KEY (mandt, matnr)
);

-- Material descriptions
CREATE TABLE makt (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  matnr   VARCHAR2(40) NOT NULL,
  spras   VARCHAR2(1)  NOT NULL,
  maktx   VARCHAR2(40),
  maktg   VARCHAR2(40),                   -- Upper-case for search
  CONSTRAINT pk_makt PRIMARY KEY (mandt, matnr, spras)
);

-- Material plant data
CREATE TABLE marc (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  matnr   VARCHAR2(40) NOT NULL,
  werks   VARCHAR2(4)  NOT NULL,
  mmsta   VARCHAR2(2),                    -- Plant-specific status
  ladgr   VARCHAR2(4),                    -- Loading group
  mtvfp   VARCHAR2(2),                    -- Availability check group
  prctr   VARCHAR2(10),                   -- Profit center
  dispo   VARCHAR2(3),                    -- MRP controller
  lvorm   VARCHAR2(1),
  CONSTRAINT pk_marc PRIMARY KEY (mandt, matnr, werks)
);

-- Material sales data
CREATE TABLE mvke (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  matnr   VARCHAR2(40) NOT NULL,
  vkorg   VARCHAR2(4)  NOT NULL,
  vtweg   VARCHAR2(2)  NOT NULL,
  vmsta   VARCHAR2(2),                    -- Distribution-chain status
  dwerk   VARCHAR2(4),                    -- Delivering plant
  mtpos   VARCHAR2(4),                    -- Item category group
  kondm   VARCHAR2(2),                    -- Material pricing group
  ktgrm   VARCHAR2(2),                    -- Account assignment group
  prodh   VARCHAR2(18),                   -- Product hierarchy
  vrkme   VARCHAR2(3),                    -- Sales unit
  aumng   NUMBER(13,3),                   -- Minimum order qty
  lvorm   VARCHAR2(1),
  CONSTRAINT pk_mvke PRIMARY KEY (mandt, matnr, vkorg, vtweg)
);

/* =====================================================================
   4. PRICING CONDITIONS (S/4: PRCD_ELEMENTS replaces KONV)
   ===================================================================== */

CREATE TABLE prcd_elements (
  client  VARCHAR2(3)  DEFAULT '100' NOT NULL,
  knumv   VARCHAR2(10) NOT NULL,          -- Condition document number
  kposn   VARCHAR2(6)  NOT NULL,          -- Item (000000 = header)
  stunr   VARCHAR2(3)  NOT NULL,          -- Step number
  zaehk   VARCHAR2(3)  NOT NULL,          -- Condition counter
  kschl   VARCHAR2(4),                    -- Condition type (PR00, K007, MWST ...)
  kdatu   DATE,                           -- Condition pricing date
  krech   VARCHAR2(1),                    -- Calculation type
  kbetr   NUMBER(24,9),                   -- Rate
  waers   VARCHAR2(5),
  kpein   NUMBER(5),                      -- Pricing unit
  kmein   VARCHAR2(3),                    -- Condition unit
  kawrt   NUMBER(24,9),                   -- Condition base value
  kwert   NUMBER(24,9),                   -- Condition value
  koaid   VARCHAR2(1),                    -- Condition class (B price, A discount, D tax)
  kstat   VARCHAR2(1),                    -- Statistical
  kinak   VARCHAR2(1),                    -- Inactive
  kherk   VARCHAR2(1),                    -- Origin (A automatic, C manual)
  CONSTRAINT pk_prcd_elements PRIMARY KEY (client, knumv, kposn, stunr, zaehk)
);

/* =====================================================================
   5. SALES DOCUMENTS (orders, quotations, returns, credit memo requests)
   ===================================================================== */

-- Sales document header
CREATE TABLE vbak (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vbeln   VARCHAR2(10) NOT NULL,          -- Sales document
  erdat   DATE,
  erzet   VARCHAR2(6),
  ernam   VARCHAR2(12),
  aedat   DATE,                           -- Last changed on
  audat   DATE,                           -- Document date
  vbtyp   VARCHAR2(4),                    -- Document category (C order, B quote, H return ...)
  trvog   VARCHAR2(1),                    -- Transaction group
  auart   VARCHAR2(4),                    -- Sales document type
  augru   VARCHAR2(3),                    -- Order reason
  lifsk   VARCHAR2(2),                    -- Delivery block
  faksk   VARCHAR2(2),                    -- Billing block
  netwr   NUMBER(15,2),                   -- Net value
  waerk   VARCHAR2(5),                    -- Document currency
  vkorg   VARCHAR2(4),
  vtweg   VARCHAR2(2),
  spart   VARCHAR2(2),
  vkgrp   VARCHAR2(3),
  vkbur   VARCHAR2(4),
  guebg   DATE,                           -- Valid from (contracts/quotes)
  gueen   DATE,                           -- Valid to
  knumv   VARCHAR2(10),                   -- Link to PRCD_ELEMENTS
  vdatu   DATE,                           -- Requested delivery date
  bstnk   VARCHAR2(35),                   -- Customer PO number
  bstdk   DATE,                           -- Customer PO date
  kunnr   VARCHAR2(10),                   -- Sold-to party
  kkber   VARCHAR2(4),                    -- Credit control area
  bukrs_vf VARCHAR2(4),                   -- Billing company code
  vgbel   VARCHAR2(10),                   -- Reference document (e.g. quotation)
  -- Statuses (moved here from VBUK in S/4HANA)
  gbstk   VARCHAR2(1),                    -- Overall status
  abstk   VARCHAR2(1),                    -- Rejection status
  lfstk   VARCHAR2(1),                    -- Delivery status
  fkstk   VARCHAR2(1),                    -- Billing status
  cmgst   VARCHAR2(1),                    -- Overall credit status
  spstg   VARCHAR2(1),                    -- Overall block status
  CONSTRAINT pk_vbak PRIMARY KEY (mandt, vbeln)
);
CREATE INDEX ix_vbak_kunnr ON vbak (mandt, kunnr);
CREATE INDEX ix_vbak_erdat ON vbak (mandt, erdat);
CREATE INDEX ix_vbak_aedat ON vbak (mandt, aedat);

-- Sales document item
CREATE TABLE vbap (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vbeln   VARCHAR2(10) NOT NULL,
  posnr   VARCHAR2(6)  NOT NULL,          -- Item number
  matnr   VARCHAR2(40),
  arktx   VARCHAR2(40),                   -- Item text
  pstyv   VARCHAR2(4),                    -- Item category (TAN ...)
  uepos   VARCHAR2(6),                    -- Higher-level item
  abgru   VARCHAR2(2),                    -- Rejection reason
  matkl   VARCHAR2(9),
  prodh   VARCHAR2(18),
  kwmeng  NUMBER(15,3),                   -- Order quantity
  vrkme   VARCHAR2(3),                    -- Sales unit
  meins   VARCHAR2(3),                    -- Base unit
  umvkz   NUMBER(5),                      -- Conversion numerator
  umvkn   NUMBER(5),                      -- Conversion denominator
  netpr   NUMBER(11,2),                   -- Net price
  kpein   NUMBER(5),                      -- Pricing unit
  kmein   VARCHAR2(3),
  netwr   NUMBER(15,2),                   -- Net value
  mwsbp   NUMBER(13,2),                   -- Tax amount
  waerk   VARCHAR2(5),
  werks   VARCHAR2(4),                    -- Plant
  lgort   VARCHAR2(4),                    -- Storage location
  vstel   VARCHAR2(4),                    -- Shipping point
  route   VARCHAR2(6),
  prctr   VARCHAR2(10),
  vgbel   VARCHAR2(10),                   -- Reference document
  vgpos   VARCHAR2(6),                    -- Reference item
  erdat   DATE,
  erzet   VARCHAR2(6),
  ernam   VARCHAR2(12),
  aedat   DATE,
  -- Statuses (moved here from VBUP in S/4HANA)
  gbsta   VARCHAR2(1),                    -- Overall status
  absta   VARCHAR2(1),                    -- Rejection status
  lfsta   VARCHAR2(1),                    -- Delivery status
  fksta   VARCHAR2(1),                    -- Billing status
  CONSTRAINT pk_vbap PRIMARY KEY (mandt, vbeln, posnr)
);
CREATE INDEX ix_vbap_matnr ON vbap (mandt, matnr);

-- Schedule lines
CREATE TABLE vbep (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vbeln   VARCHAR2(10) NOT NULL,
  posnr   VARCHAR2(6)  NOT NULL,
  etenr   VARCHAR2(4)  NOT NULL,          -- Schedule line number
  ettyp   VARCHAR2(2),                    -- Schedule line category (CP, CN ...)
  edatu   DATE,                           -- Delivery date
  wmeng   NUMBER(13,3),                   -- Ordered qty
  bmeng   NUMBER(13,3),                   -- Confirmed qty
  vrkme   VARCHAR2(3),
  lmeng   NUMBER(13,3),                   -- Required qty (base unit)
  meins   VARCHAR2(3),
  mbdat   DATE,                           -- Material availability date
  lddat   DATE,                           -- Loading date
  wadat   DATE,                           -- Goods issue date
  tddat   DATE,                           -- Transportation planning date
  lifsp   VARCHAR2(2),                    -- Delivery block
  CONSTRAINT pk_vbep PRIMARY KEY (mandt, vbeln, posnr, etenr)
);

-- Business data (header: POSNR = '000000', or item level)
CREATE TABLE vbkd (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vbeln   VARCHAR2(10) NOT NULL,
  posnr   VARCHAR2(6)  NOT NULL,
  zterm   VARCHAR2(4),                    -- Payment terms
  inco1   VARCHAR2(3),
  inco2   VARCHAR2(28),
  bstkd   VARCHAR2(35),                   -- Customer PO
  prsdt   DATE,                           -- Pricing date
  fkdat   DATE,                           -- Billing date
  kursk   NUMBER(9,5),                    -- Exchange rate
  kdgrp   VARCHAR2(2),
  bzirk   VARCHAR2(6),
  konda   VARCHAR2(2),
  pltyp   VARCHAR2(2),
  ktgrd   VARCHAR2(2),
  CONSTRAINT pk_vbkd PRIMARY KEY (mandt, vbeln, posnr)
);

-- Partners on SD documents (orders, deliveries, billing)
CREATE TABLE vbpa (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vbeln   VARCHAR2(10) NOT NULL,
  posnr   VARCHAR2(6)  NOT NULL,          -- 000000 = header partner
  parvw   VARCHAR2(2)  NOT NULL,          -- AG, WE, RE, RG, ZM ...
  kunnr   VARCHAR2(10),
  lifnr   VARCHAR2(10),
  pernr   VARCHAR2(8),
  parnr   VARCHAR2(10),                   -- Contact person
  adrnr   VARCHAR2(10),
  land1   VARCHAR2(3),
  CONSTRAINT pk_vbpa PRIMARY KEY (mandt, vbeln, posnr, parvw)
);
CREATE INDEX ix_vbpa_kunnr ON vbpa (mandt, kunnr, parvw);

/* =====================================================================
   6. DOCUMENT FLOW (S/4: GUID key)
   ===================================================================== */

CREATE TABLE vbfa (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  ruuid   RAW(16)      DEFAULT SYS_GUID() NOT NULL,
  vbelv   VARCHAR2(10),                   -- Preceding document
  posnv   VARCHAR2(6),                    -- Preceding item
  vbtyp_v VARCHAR2(4),                    -- Preceding category
  vbeln   VARCHAR2(10),                   -- Subsequent document
  posnn   VARCHAR2(6),                    -- Subsequent item
  vbtyp_n VARCHAR2(4),                    -- Subsequent category
  rfmng   NUMBER(15,3),                   -- Referenced quantity
  meins   VARCHAR2(3),
  rfwrt   NUMBER(15,2),                   -- Referenced value
  waers   VARCHAR2(5),
  matnr   VARCHAR2(40),
  plmin   VARCHAR2(1),                    -- + / - quantity effect
  erdat   DATE,
  erzet   VARCHAR2(6),
  CONSTRAINT pk_vbfa PRIMARY KEY (mandt, ruuid)
);
CREATE INDEX ix_vbfa_prec ON vbfa (mandt, vbelv, posnv);
CREATE INDEX ix_vbfa_subs ON vbfa (mandt, vbeln, posnn);

/* =====================================================================
   7. OUTBOUND DELIVERIES
   ===================================================================== */

CREATE TABLE likp (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vbeln   VARCHAR2(10) NOT NULL,          -- Delivery
  ernam   VARCHAR2(12),
  erzet   VARCHAR2(6),
  erdat   DATE,
  aedat   DATE,
  vstel   VARCHAR2(4),                    -- Shipping point
  vkorg   VARCHAR2(4),
  lfart   VARCHAR2(4),                    -- Delivery type
  vbtyp   VARCHAR2(4),                    -- J delivery, T returns delivery
  route   VARCHAR2(6),
  lfdat   DATE,                           -- Delivery date
  kodat   DATE,                           -- Picking date
  lddat   DATE,                           -- Loading date
  wadat   DATE,                           -- Planned goods issue
  wadat_ist DATE,                         -- Actual goods issue
  kunnr   VARCHAR2(10),                   -- Ship-to
  kunag   VARCHAR2(10),                   -- Sold-to
  btgew   NUMBER(15,3),                   -- Total weight
  ntgew   NUMBER(15,3),
  gewei   VARCHAR2(3),
  anzpk   NUMBER(5),                      -- Number of packages
  inco1   VARCHAR2(3),
  inco2   VARCHAR2(28),
  lifsk   VARCHAR2(2),
  -- Statuses (from VBUK in ECC)
  gbstk   VARCHAR2(1),
  kostk   VARCHAR2(1),                    -- Picking status
  wbstk   VARCHAR2(1),                    -- Goods movement status
  fkstk   VARCHAR2(1),                    -- Billing status
  CONSTRAINT pk_likp PRIMARY KEY (mandt, vbeln)
);
CREATE INDEX ix_likp_kunnr ON likp (mandt, kunnr);

CREATE TABLE lips (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vbeln   VARCHAR2(10) NOT NULL,
  posnr   VARCHAR2(6)  NOT NULL,
  pstyv   VARCHAR2(4),
  matnr   VARCHAR2(40),
  arktx   VARCHAR2(40),
  matkl   VARCHAR2(9),
  werks   VARCHAR2(4),
  lgort   VARCHAR2(4),
  charg   VARCHAR2(10),                   -- Batch
  lfimg   NUMBER(13,3),                   -- Delivered qty (sales unit)
  vrkme   VARCHAR2(3),
  lgmng   NUMBER(13,3),                   -- Delivered qty (base unit)
  meins   VARCHAR2(3),
  ntgew   NUMBER(15,3),
  brgew   NUMBER(15,3),
  gewei   VARCHAR2(3),
  vgbel   VARCHAR2(10),                   -- Reference sales order
  vgpos   VARCHAR2(6),                    -- Reference order item
  prctr   VARCHAR2(10),
  erdat   DATE,
  erzet   VARCHAR2(6),
  ernam   VARCHAR2(12),
  aedat   DATE,
  -- Statuses (from VBUP in ECC)
  gbsta   VARCHAR2(1),
  kosta   VARCHAR2(1),
  wbsta   VARCHAR2(1),
  fksta   VARCHAR2(1),
  CONSTRAINT pk_lips PRIMARY KEY (mandt, vbeln, posnr)
);
CREATE INDEX ix_lips_vgbel ON lips (mandt, vgbel, vgpos);

/* =====================================================================
   8. BILLING DOCUMENTS
   ===================================================================== */

CREATE TABLE vbrk (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vbeln   VARCHAR2(10) NOT NULL,          -- Billing document
  fkart   VARCHAR2(4),                    -- Billing type
  fktyp   VARCHAR2(1),
  vbtyp   VARCHAR2(4),                    -- M invoice, N cancellation, O credit memo
  waerk   VARCHAR2(5),
  vkorg   VARCHAR2(4),
  vtweg   VARCHAR2(2),
  spart   VARCHAR2(2),
  knumv   VARCHAR2(10),                   -- Link to PRCD_ELEMENTS
  fkdat   DATE,                           -- Billing date
  gjahr   VARCHAR2(4),                    -- Fiscal year
  poper   VARCHAR2(3),                    -- Posting period
  bukrs   VARCHAR2(4),
  netwr   NUMBER(15,2),
  mwsbk   NUMBER(13,2),                   -- Tax amount
  kurrf   NUMBER(9,5),                    -- Exchange rate to FI
  kunrg   VARCHAR2(10),                   -- Payer
  kunag   VARCHAR2(10),                   -- Sold-to
  zterm   VARCHAR2(4),
  xblnr   VARCHAR2(16),                   -- Reference (e.g. GST invoice no.)
  belnr   VARCHAR2(10),                   -- Accounting document
  rfbsk   VARCHAR2(1),                    -- Posting status to FI
  fksto   VARCHAR2(1),                    -- Cancelled flag
  sfakn   VARCHAR2(10),                   -- Cancelled billing document
  ernam   VARCHAR2(12),
  erzet   VARCHAR2(6),
  erdat   DATE,
  aedat   DATE,
  -- Statuses
  gbstk   VARCHAR2(1),
  buchk   VARCHAR2(1),                    -- Posting status
  CONSTRAINT pk_vbrk PRIMARY KEY (mandt, vbeln)
);
CREATE INDEX ix_vbrk_fkdat ON vbrk (mandt, fkdat);
CREATE INDEX ix_vbrk_kunrg ON vbrk (mandt, kunrg);

CREATE TABLE vbrp (
  mandt   VARCHAR2(3)  DEFAULT '100' NOT NULL,
  vbeln   VARCHAR2(10) NOT NULL,
  posnr   VARCHAR2(6)  NOT NULL,
  fkimg   NUMBER(13,3),                   -- Billed quantity
  vrkme   VARCHAR2(3),
  fklmg   NUMBER(13,3),                   -- Billed qty (base unit)
  meins   VARCHAR2(3),
  netwr   NUMBER(15,2),
  mwsbp   NUMBER(13,2),
  wavwr   NUMBER(13,2),                   -- Cost
  matnr   VARCHAR2(40),
  arktx   VARCHAR2(40),
  matkl   VARCHAR2(9),
  prodh   VARCHAR2(18),
  pstyv   VARCHAR2(4),
  werks   VARCHAR2(4),
  prctr   VARCHAR2(10),
  vgbel   VARCHAR2(10),                   -- Reference document (delivery)
  vgpos   VARCHAR2(6),
  vgtyp   VARCHAR2(4),
  aubel   VARCHAR2(10),                   -- Sales order
  aupos   VARCHAR2(6),
  erdat   DATE,
  erzet   VARCHAR2(6),
  ernam   VARCHAR2(12),
  CONSTRAINT pk_vbrp PRIMARY KEY (mandt, vbeln, posnr)
);
CREATE INDEX ix_vbrp_aubel ON vbrp (mandt, aubel, aupos);
CREATE INDEX ix_vbrp_vgbel ON vbrp (mandt, vgbel, vgpos);

/* =====================================================================
   9. MINIMAL CUSTOMIZING SEED DATA
   ===================================================================== */

INSERT INTO t001  (bukrs, butxt, ort01, land1, waers, spras, ktopl)
  VALUES ('IN01', 'Demo India Pvt Ltd', 'Pune', 'IN', 'INR', 'E', 'INT');
INSERT INTO t001w (werks, name1, bwkey, vkorg, vtweg, spart, land1, regio, ort01, pstlz)
  VALUES ('1000', 'Pune Plant', '1000', '1000', '10', '00', 'IN', '13', 'Pune', '411001');
INSERT INTO tvko  (vkorg, waers, bukrs) VALUES ('1000', 'INR', 'IN01');
INSERT INTO tvtw  (vtweg, vtext) VALUES ('10', 'Direct sales');
INSERT INTO tvtw  (vtweg, vtext) VALUES ('20', 'Distributors');
INSERT INTO tspa  (spart, vtext) VALUES ('00', 'Cross-division');
INSERT INTO tvta  (vkorg, vtweg, spart) VALUES ('1000', '10', '00');
INSERT INTO tvta  (vkorg, vtweg, spart) VALUES ('1000', '20', '00');
INSERT INTO tvak  (auart, vbtyp, numki, bezei) VALUES ('OR', 'C', '01', 'Standard Order');
INSERT INTO tvak  (auart, vbtyp, numki, bezei) VALUES ('RE', 'H', '02', 'Returns');
INSERT INTO tvak  (auart, vbtyp, numki, bezei) VALUES ('QT', 'B', '03', 'Quotation');
INSERT INTO tvak  (auart, vbtyp, numki, bezei) VALUES ('CR', 'K', '04', 'Credit Memo Request');
INSERT INTO tvlk  (lfart, vbtyp, bezei) VALUES ('LF', 'J', 'Outbound Delivery');
INSERT INTO tvlk  (lfart, vbtyp, bezei) VALUES ('LR', 'T', 'Returns Delivery');
INSERT INTO tvfk  (fkart, vbtyp, fktyp, bezei) VALUES ('F2', 'M', 'L', 'Invoice');
INSERT INTO tvfk  (fkart, vbtyp, fktyp, bezei) VALUES ('S1', 'N', 'L', 'Invoice Cancellation');
INSERT INTO tvfk  (fkart, vbtyp, fktyp, bezei) VALUES ('G2', 'O', 'A', 'Credit Memo');
INSERT INTO tvfk  (fkart, vbtyp, fktyp, bezei) VALUES ('RE', 'O', 'A', 'Credit for Returns');
COMMIT;

/* =====================================================================
   10. CDC PREP FOR DEBEZIUM (LogMiner needs full-row supplemental logging)
       Database-level: ALTER DATABASE ADD SUPPLEMENTAL LOG DATA;  (as SYSDBA, CDB)
   ===================================================================== */

BEGIN
  FOR t IN (SELECT table_name FROM user_tables
            WHERE table_name IN (
              'T001','T001W','TVKO','TVTW','TSPA','TVTA','TVAK','TVLK','TVFK',
              'BUT000','CVI_CUST_LINK','KNA1','KNB1','KNVV','KNVP',
              'MARA','MAKT','MARC','MVKE','PRCD_ELEMENTS',
              'VBAK','VBAP','VBEP','VBKD','VBPA','VBFA',
              'LIKP','LIPS','VBRK','VBRP')) LOOP
    EXECUTE IMMEDIATE 'ALTER TABLE ' || t.table_name ||
                      ' ADD SUPPLEMENTAL LOG DATA (ALL) COLUMNS';
  END LOOP;
END;
/
