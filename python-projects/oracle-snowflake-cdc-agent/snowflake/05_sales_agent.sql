/* =====================================================================
   SAP Sales Agent: ask questions in plain English about orders,
   deliveries and billing (Snowflake Cortex Agent + Cortex Analyst).

   Builds on the Gold tables:
     SAP_GOLD.SALES.SALES_DOC_HDR   one row per sales document
     SAP_GOLD.SALES.SALES_DOC_POS   one row per sales document item
     SAP_GOLD.SALES.DEL_DOC_POS     one row per delivery item

   1. Grants (admin)
   2. Semantic view SAP_GOLD.SALES.SV_SAP_SALES: tables, relationships,
      business names, synonyms, metrics, SQL rules for the AI
   3. Agent SAP_GOLD.SALES.SAP_SALES_AGENT using that semantic view
   4. Tests

   Then: Snowsight > AI & ML > Agents > SAP Sales Assistant > ask a question.
   ===================================================================== */

/* ---------------------------------------------------------------------
   1. Grants (run once as an admin)
   --------------------------------------------------------------------- */
USE ROLE ACCOUNTADMIN;

-- Cortex Agent and Cortex Analyst access
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_AGENT_USER TO ROLE SAP_TRANSFORM_ROLE;

-- Object creation in the Gold schema
GRANT CREATE SEMANTIC VIEW ON SCHEMA SAP_GOLD.SALES TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE AGENT         ON SCHEMA SAP_GOLD.SALES TO ROLE SAP_TRANSFORM_ROLE;

-- Only if agent calls fail with "model not available in your region"
-- (common on trial accounts): let Cortex use models in another region.
-- ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';

/* ---------------------------------------------------------------------
   2. Semantic view: what the tables mean, in business language
   --------------------------------------------------------------------- */
USE ROLE SAP_TRANSFORM_ROLE;
USE WAREHOUSE SAP_TRANSFORM_WH;

CREATE OR REPLACE SEMANTIC VIEW SAP_GOLD.SALES.SV_SAP_SALES
  TABLES (
    hdr AS SAP_GOLD.SALES.SALES_DOC_HDR
      PRIMARY KEY (CLIENT, SALES_DOC)
      WITH SYNONYMS ('sales orders', 'orders', 'sales documents', 'order headers')
      COMMENT = 'One row per SAP sales document: orders, quotations, returns',
    pos AS SAP_GOLD.SALES.SALES_DOC_POS
      PRIMARY KEY (CLIENT, SALES_DOC, ITEM)
      WITH SYNONYMS ('order items', 'order lines', 'line items', 'sales items')
      COMMENT = 'One row per sales document item, with pricing, confirmation, delivery and billing',
    del AS SAP_GOLD.SALES.DEL_DOC_POS
      PRIMARY KEY (CLIENT, DELIVERY_DOC, ITEM)
      WITH SYNONYMS ('deliveries', 'shipments', 'delivery items', 'outbound deliveries')
      COMMENT = 'One row per delivery item, outbound and returns, with goods issue and billing'
  )
  RELATIONSHIPS (
    item_to_order    AS pos (CLIENT, SALES_DOC) REFERENCES hdr,
    delivery_to_item AS del (CLIENT, SALES_DOC, SALES_ITEM) REFERENCES pos
  )
  DIMENSIONS (
    -- Sales document header
    hdr.sales_doc            AS hdr.SALES_DOC
      WITH SYNONYMS = ('order number', 'sales order number', 'document number'),
    hdr.doc_category         AS hdr.DOC_CATEGORY_TEXT
      WITH SYNONYMS = ('document category')
      COMMENT = 'Order, Quotation, Return or Credit memo request',
    hdr.doc_type             AS hdr.DOC_TYPE_TEXT
      COMMENT = 'Sales document type text, e.g. Standard Order',
    hdr.order_date           AS hdr.DOC_DATE
      WITH SYNONYMS = ('order date', 'document date', 'date ordered')
      COMMENT = 'Date the sales document was created in SAP',
    hdr.order_month          AS DATE_TRUNC('month', hdr.DOC_DATE)
      WITH SYNONYMS = ('month', 'order month'),
    hdr.requested_delivery_date AS hdr.REQ_DELIVERY_DATE
      WITH SYNONYMS = ('requested date', 'customer requested date'),
    hdr.customer             AS hdr.SOLD_TO_NAME
      WITH SYNONYMS = ('customer name', 'sold-to', 'client', 'account')
      COMMENT = 'Sold-to customer name',
    hdr.customer_number      AS hdr.SOLD_TO,
    hdr.customer_city        AS hdr.SOLD_TO_CITY
      WITH SYNONYMS = ('city'),
    hdr.customer_region      AS hdr.SOLD_TO_REGION
      WITH SYNONYMS = ('state', 'region code')
      COMMENT = 'Indian state code of the customer, e.g. 13 = Maharashtra',
    hdr.sales_office         AS hdr.SALES_OFFICE
      COMMENT = 'PUN1 Pune, BLR1 Bengaluru, DEL1 Delhi',
    hdr.sales_channel        AS DECODE(hdr.DISTR_CHANNEL, '10', 'Direct sales', '20', 'Distributors', hdr.DISTR_CHANNEL)
      WITH SYNONYMS = ('distribution channel', 'channel'),
    hdr.overall_status       AS hdr.OVERALL_STATUS_TEXT
      WITH SYNONYMS = ('order status'),
    hdr.delivery_status      AS hdr.DELIVERY_STATUS_TEXT,
    hdr.billing_status       AS hdr.BILLING_STATUS_TEXT,
    hdr.is_credit_blocked    AS hdr.IS_CREDIT_BLOCKED
      WITH SYNONYMS = ('credit block', 'blocked for credit'),
    hdr.customer_po          AS hdr.CUSTOMER_PO
      WITH SYNONYMS = ('purchase order', 'PO number'),

    -- Sales document item
    pos.item_number          AS pos.ITEM,
    pos.material             AS pos.MATERIAL
      WITH SYNONYMS = ('product code', 'material number', 'SKU'),
    pos.material_description AS pos.MATERIAL_TEXT
      WITH SYNONYMS = ('product', 'product name', 'item description'),
    pos.material_group       AS pos.MATERIAL_GROUP
      WITH SYNONYMS = ('product group', 'product category'),
    pos.plant                AS pos.PLANT
      COMMENT = '1000 Pune Plant - Bhosari, 1100 Chakan Plant',
    pos.is_rejected          AS pos.IS_REJECTED
      WITH SYNONYMS = ('rejected', 'cancelled item'),
    pos.has_backorder        AS pos.HAS_BACKORDER
      WITH SYNONYMS = ('backorder', 'back order'),

    -- Delivery item
    del.delivery_number      AS del.DELIVERY_DOC
      WITH SYNONYMS = ('delivery', 'shipment number'),
    del.goods_issue_date     AS del.ACTUAL_GOODS_ISSUE_DATE
      WITH SYNONYMS = ('ship date', 'shipped date', 'dispatch date'),
    del.ship_to              AS del.SHIP_TO_NAME
      WITH SYNONYMS = ('ship-to', 'delivery address'),
    del.ship_to_city         AS del.SHIP_TO_CITY,
    del.is_return            AS del.IS_RETURN
      WITH SYNONYMS = ('returns delivery'),
    del.is_goods_issued      AS del.IS_GOODS_ISSUED
      WITH SYNONYMS = ('shipped', 'dispatched'),
    del.is_shipped_not_billed AS del.IS_SHIPPED_NOT_BILLED
      WITH SYNONYMS = ('unbilled shipment', 'shipped not invoiced')
  )
  METRICS (
    -- Orders
    hdr.order_count          AS COUNT(DISTINCT hdr.SALES_DOC)
      WITH SYNONYMS = ('number of orders', 'orders count'),
    hdr.order_value          AS SUM(hdr.NET_VALUE)
      WITH SYNONYMS = ('order value', 'net order value', 'sales value', 'bookings')
      COMMENT = 'Net value in INR excluding tax and rejected items',
    hdr.order_value_with_tax AS SUM(hdr.GROSS_VALUE)
      WITH SYNONYMS = ('gross value', 'value including GST'),
    hdr.open_billing_value   AS SUM(hdr.OPEN_BILLING_VALUE)
      WITH SYNONYMS = ('open order value', 'backlog value', 'unbilled order value'),
    hdr.average_order_value  AS AVG(hdr.NET_VALUE)
      WITH SYNONYMS = ('AOV', 'average order size'),

    -- Items
    pos.ordered_quantity     AS SUM(pos.ORDER_QTY)
      WITH SYNONYMS = ('quantity ordered', 'units ordered'),
    pos.item_value           AS SUM(pos.EFFECTIVE_NET_VALUE)
      WITH SYNONYMS = ('product sales', 'sales by product')
      COMMENT = 'Net item value in INR, rejected items count as 0',
    pos.discount_value       AS SUM(pos.DISCOUNT_VALUE)
      WITH SYNONYMS = ('discount', 'discounts given'),
    pos.gst_value            AS SUM(pos.TAX_VALUE)
      WITH SYNONYMS = ('GST', 'tax'),
    pos.open_delivery_quantity AS SUM(pos.OPEN_DELIVERY_QTY)
      WITH SYNONYMS = ('backlog quantity', 'quantity to ship'),
    pos.billed_revenue       AS SUM(pos.NET_BILLED_VALUE)
      WITH SYNONYMS = ('revenue', 'invoiced revenue', 'billed value', 'net revenue')
      COMMENT = 'Invoices minus cancellations and credit memos, in INR',
    pos.billed_margin        AS SUM(pos.NET_BILLED_MARGIN)
      WITH SYNONYMS = ('margin', 'gross margin', 'profit'),
    pos.fill_rate_pct        AS ROUND(SUM(pos.DELIVERED_QTY) / NULLIF(SUM(IFF(pos.IS_REJECTED, 0, pos.ORDER_QTY)), 0) * 100, 1)
      WITH SYNONYMS = ('fill rate', 'delivered percentage'),

    -- Deliveries
    del.delivery_count       AS COUNT(DISTINCT del.DELIVERY_DOC)
      WITH SYNONYMS = ('number of deliveries', 'shipments count'),
    del.shipped_quantity     AS SUM(del.DELIVERY_QTY_SIGNED)
      WITH SYNONYMS = ('quantity shipped', 'units shipped')
      COMMENT = 'Returns are negative',
    del.shipped_value        AS SUM(del.DELIVERY_NET_VALUE_SIGNED)
      WITH SYNONYMS = ('value shipped'),
    del.shipped_not_billed_value AS SUM(IFF(del.IS_SHIPPED_NOT_BILLED, del.DELIVERY_NET_VALUE, 0))
      WITH SYNONYMS = ('unbilled value', 'revenue at risk'),
    del.on_time_goods_issue_pct AS ROUND(AVG(IFF(del.IS_GOODS_ISSUED, IFF(del.GOODS_ISSUE_ON_TIME, 100, 0), NULL)), 1)
      WITH SYNONYMS = ('on-time shipping', 'on time delivery', 'OTD'),
    del.avg_days_order_to_ship AS ROUND(AVG(del.DAYS_ORDER_TO_GOODS_ISSUE), 1)
      WITH SYNONYMS = ('lead time', 'days to ship', 'order to ship time')
  )
  COMMENT = 'SAP S/4HANA Sales & Distribution: orders, items, deliveries and billing (INR)'
  AI_SQL_GENERATION 'All amounts are in Indian Rupees (INR). Unless the user asks about quotations or returns, restrict order questions to doc_category = ''Order''. Revenue questions use billed_revenue (invoices minus cancellations and credit memos); never sum billing documents without that sign. Order value questions use order_value, which already excludes rejected items. For "this month" or "last month" use order_date (or goods_issue_date for shipments) relative to CURRENT_DATE. Show customer and product names, not codes, unless codes are asked for.';

/* ---------------------------------------------------------------------
   3. The agent
   --------------------------------------------------------------------- */
CREATE OR REPLACE AGENT SAP_GOLD.SALES.SAP_SALES_AGENT
  COMMENT = 'Answers questions about SAP sales orders, deliveries and billing'
  PROFILE = '{"display_name": "SAP Sales Assistant"}'
  FROM SPECIFICATION
  $$
  models:
    orchestration: auto

  instructions:
    response: >
      Answer concisely for business users. Format amounts in INR with thousands
      separators (for example INR 12,45,000). When you return a list, show at
      most 20 rows and say how many there are in total. Mention the date range
      your answer covers. If the data cannot answer the question, say so.
    orchestration: >
      Use the SAP_Sales_Analyst tool for every question about orders, order items,
      customers, products, deliveries, shipments, backlog, revenue, billing,
      discounts, GST or on-time performance.
    sample_questions:
      - question: "What was our net order value by customer this month?"
      - question: "Which orders are blocked for credit?"
      - question: "Show the open order backlog by product."
      - question: "What is our billed revenue and margin by month?"
      - question: "Which deliveries were shipped but not yet invoiced?"
      - question: "What is the on-time shipping percentage by plant?"

  tools:
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "SAP_Sales_Analyst"
        description: >
          Generates and runs SQL over SAP sales documents, sales items and delivery
          items: customers, materials, order value, backlog, deliveries, billed
          revenue, margin, discounts, GST and delivery KPIs.

  tool_resources:
    SAP_Sales_Analyst:
      semantic_view: "SAP_GOLD.SALES.SV_SAP_SALES"
      execution_environment:
        type: "warehouse"
        warehouse: "SAP_TRANSFORM_WH"
  $$;

/* ---------------------------------------------------------------------
   4. Tests
   --------------------------------------------------------------------- */
DESCRIBE SEMANTIC VIEW SAP_GOLD.SALES.SV_SAP_SALES;
DESCRIBE AGENT SAP_GOLD.SALES.SAP_SALES_AGENT;

-- The semantic view can be queried directly with SQL as well
SELECT * FROM SEMANTIC_VIEW(
  SAP_GOLD.SALES.SV_SAP_SALES
  DIMENSIONS hdr.customer
  METRICS hdr.order_count, hdr.order_value, hdr.open_billing_value
) ORDER BY order_value DESC;

/* ---------------------------------------------------------------------
   5. Optional: let business users chat with the agent (read-only)
   --------------------------------------------------------------------- */
-- USE ROLE SECURITYADMIN;
-- CREATE ROLE IF NOT EXISTS SAP_SALES_READER;
-- GRANT DATABASE ROLE SNOWFLAKE.CORTEX_AGENT_USER     TO ROLE SAP_SALES_READER;
-- GRANT USAGE  ON DATABASE SAP_GOLD                    TO ROLE SAP_SALES_READER;
-- GRANT USAGE  ON SCHEMA   SAP_GOLD.SALES              TO ROLE SAP_SALES_READER;
-- GRANT SELECT ON ALL DYNAMIC TABLES IN SCHEMA SAP_GOLD.SALES TO ROLE SAP_SALES_READER;
-- GRANT SELECT ON SEMANTIC VIEW SAP_GOLD.SALES.SV_SAP_SALES  TO ROLE SAP_SALES_READER;
-- GRANT USAGE  ON AGENT SAP_GOLD.SALES.SAP_SALES_AGENT       TO ROLE SAP_SALES_READER;
-- GRANT USAGE  ON WAREHOUSE SAP_TRANSFORM_WH           TO ROLE SAP_SALES_READER;
-- GRANT ROLE SAP_SALES_READER TO USER <business_user>;
