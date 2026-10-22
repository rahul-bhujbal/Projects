/* =====================================================================
   Business changes to test CDC end to end (run as SAPSD in FREEPDB1).
   One transaction, four kinds of change:
     1. UPDATE  release the credit block on order 0000010022
     2. INSERT  new order 0000019001 (header, item, schedule line,
                business data, partners, pricing)
     3. UPDATE  reject item 000010 of order 0000010023, recalc header value
     4. DELETE  open quotation 0020000002 (all its rows)
   Re-runnable: order 0000019001 is deleted and re-created each time,
   which also produces delete + insert events.
   ===================================================================== */
SET FEEDBACK ON

-- 1. Credit release
UPDATE vbak
   SET cmgst = 'A', spstg = 'A', aedat = TRUNC(SYSDATE)
 WHERE mandt = '100' AND vbeln = '0000010022';

-- 2. New order (delete first so the script can be re-run)
DELETE FROM prcd_elements WHERE client = '100' AND knumv = '0000099001';
DELETE FROM vbpa WHERE mandt = '100' AND vbeln = '0000019001';
DELETE FROM vbkd WHERE mandt = '100' AND vbeln = '0000019001';
DELETE FROM vbep WHERE mandt = '100' AND vbeln = '0000019001';
DELETE FROM vbap WHERE mandt = '100' AND vbeln = '0000019001';
DELETE FROM vbak WHERE mandt = '100' AND vbeln = '0000019001';

INSERT INTO vbak (mandt, vbeln, erdat, erzet, ernam, audat, vbtyp, trvog, auart,
                  netwr, waerk, vkorg, vtweg, spart, vkgrp, vkbur, knumv, vdatu,
                  bstnk, bstdk, kunnr, kkber, bukrs_vf,
                  gbstk, abstk, lfstk, cmgst, spstg)
VALUES ('100', '0000019001', TRUNC(SYSDATE), TO_CHAR(SYSDATE, 'HH24MISS'), 'SD_CLERK01',
        TRUNC(SYSDATE), 'C', '0', 'OR',
        49000.00, 'INR', '1000', '10', '00', '101', 'PUN1', '0000099001', TRUNC(SYSDATE) + 5,
        'PO/SHAKTI/CDC-TEST', TRUNC(SYSDATE), '0001000001', '1000', 'IN01',
        'A', 'A', 'A', 'A', 'A');

INSERT INTO vbap (mandt, vbeln, posnr, matnr, arktx, pstyv, matkl, prodh,
                  kwmeng, vrkme, meins, umvkz, umvkn, netpr, kpein, kmein,
                  netwr, mwsbp, waerk, werks, lgort, vstel, route, prctr,
                  erdat, erzet, ernam, gbsta, absta, lfsta)
VALUES ('100', '0000019001', '000010', 'MCB-C32-3P', 'Miniature Circuit Breaker C32 3P', 'TAN',
        'ELE-MCB', '001001002',
        50, 'EA', 'EA', 1, 1, 980.00, 1, 'EA',
        49000.00, 8820.00, 'INR', '1000', '0001', '1000', 'R00001', 'PC1000',
        TRUNC(SYSDATE), TO_CHAR(SYSDATE, 'HH24MISS'), 'SD_CLERK01', 'A', 'A', 'A');

INSERT INTO vbep (mandt, vbeln, posnr, etenr, ettyp, edatu, wmeng, bmeng, vrkme,
                  lmeng, meins, mbdat, lddat, wadat, tddat)
VALUES ('100', '0000019001', '000010', '0001', 'CP', TRUNC(SYSDATE) + 5, 50, 50, 'EA',
        50, 'EA', TRUNC(SYSDATE) + 3, TRUNC(SYSDATE) + 3, TRUNC(SYSDATE) + 4, TRUNC(SYSDATE) + 3);

INSERT INTO vbkd (mandt, vbeln, posnr, zterm, inco1, inco2, bstkd, prsdt, kursk,
                  kdgrp, bzirk, konda, pltyp, ktgrd)
VALUES ('100', '0000019001', '000000', 'NT30', 'DAP', 'Pune', 'PO/SHAKTI/CDC-TEST',
        TRUNC(SYSDATE), 1, '01', 'IN-WST', '01', '01', '01');

INSERT INTO vbpa (mandt, vbeln, posnr, parvw, kunnr, adrnr, land1)
  SELECT '100', '0000019001', '000000', parvw, '0001000001', '0000005000', 'IN'
  FROM (SELECT 'AG' AS parvw FROM dual UNION ALL SELECT 'WE' FROM dual
        UNION ALL SELECT 'RE' FROM dual UNION ALL SELECT 'RG' FROM dual);

INSERT INTO prcd_elements (client, knumv, kposn, stunr, zaehk, kschl, kdatu, krech,
                           kbetr, waers, kpein, kmein, kawrt, kwert, koaid, kherk)
VALUES ('100', '0000099001', '000010', '010', '001', 'PR00', TRUNC(SYSDATE), 'C',
        980, 'INR', 1, 'EA', 50, 49000, 'B', 'A');
INSERT INTO prcd_elements (client, knumv, kposn, stunr, zaehk, kschl, kdatu, krech,
                           kbetr, waers, kawrt, kwert, koaid, kherk)
VALUES ('100', '0000099001', '000010', '800', '001', 'JOCG', TRUNC(SYSDATE), 'A',
        9, 'INR', 49000, 4410, 'D', 'A');
INSERT INTO prcd_elements (client, knumv, kposn, stunr, zaehk, kschl, kdatu, krech,
                           kbetr, waers, kawrt, kwert, koaid, kherk)
VALUES ('100', '0000099001', '000010', '810', '001', 'JOSG', TRUNC(SYSDATE), 'A',
        9, 'INR', 49000, 4410, 'D', 'A');

-- 3. Reject the first item of order 0000010023 and recalculate the header value
UPDATE vbap
   SET abgru = '02', absta = 'C', gbsta = 'C', aedat = TRUNC(SYSDATE)
 WHERE mandt = '100' AND vbeln = '0000010023' AND posnr = '000010';

UPDATE vbak h
   SET netwr = (SELECT NVL(SUM(i.netwr), 0) FROM vbap i
                 WHERE i.mandt = h.mandt AND i.vbeln = h.vbeln AND i.abgru IS NULL),
       abstk = 'B',
       aedat = TRUNC(SYSDATE)
 WHERE mandt = '100' AND vbeln = '0000010023';

-- 4. Delete the open quotation
DELETE FROM prcd_elements
 WHERE client = '100'
   AND knumv = (SELECT knumv FROM vbak WHERE mandt = '100' AND vbeln = '0020000002');
DELETE FROM vbpa WHERE mandt = '100' AND vbeln = '0020000002';
DELETE FROM vbkd WHERE mandt = '100' AND vbeln = '0020000002';
DELETE FROM vbep WHERE mandt = '100' AND vbeln = '0020000002';
DELETE FROM vbap WHERE mandt = '100' AND vbeln = '0020000002';
DELETE FROM vbak WHERE mandt = '100' AND vbeln = '0020000002';

COMMIT;
