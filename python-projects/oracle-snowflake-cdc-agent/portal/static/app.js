/* Demo India Customer Portal - front-end (no frameworks, no external libraries). */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");
const store = {
  get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
};
const state = { customer: store.get("customer", ""), customers: [], cart: store.get("cart", []), oracle: false };

/* ---------- helpers ---------- */
const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
const num = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const strip0 = s => String(s ?? "").replace(/^0+(?=\d)/, "");

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  let body = null;
  try { body = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const d = body && body.detail;
    throw new Error(Array.isArray(d) ? d.map(x => x.msg).join("; ") : (d || `${res.status} ${res.statusText}`));
  }
  return body;
}

function qs(params) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, v); });
  const s = p.toString();
  return s ? "?" + s : "";
}

function toast(msg, ms = 4500) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.add("hidden"), ms);
}

function cell(row, col) {
  const v = row[col.key];
  switch (col.type) {
    case "money": return `<td class="num">${v === null || v === undefined ? "" : inr.format(v)}</td>`;
    case "num": return `<td class="num">${v === null || v === undefined ? "" : num.format(v)}</td>`;
    case "bool": return `<td>${v ? `<span class="chip ${col.bad ? "bad" : "warn"}">${esc(col.yes || "Yes")}</span>` : ""}</td>`;
    case "status": return `<td><span class="chip ${esc(row[col.code] || "")}">${esc(v || "")}</span></td>`;
    case "link": return `<td>${v ? `<a href="${col.href(row)}">${esc(strip0(v))}</a>` : ""}</td>`;
    case "doc": return `<td>${esc(strip0(v))}</td>`;
    default: return `<td>${esc(v ?? "")}</td>`;
  }
}

function table(rows, cols, { empty = "No records found.", totals = null } = {}) {
  if (!rows || !rows.length) return `<div class="table-wrap"><div class="empty">${esc(empty)}</div></div>`;
  const head = cols.map(c => `<th class="${c.type === "money" || c.type === "num" ? "num" : ""}">${esc(c.label)}</th>`).join("");
  const body = rows.map(r => `<tr>${cols.map(c => cell(r, c)).join("")}</tr>`).join("");
  let foot = "";
  if (totals) {
    foot = `<tr class="total-row">${cols.map((c, i) => {
      if (i === 0) return "<td>Total</td>";
      if (totals.includes(c.key)) {
        const sum = rows.reduce((a, r) => a + (Number(r[c.key]) || 0), 0);
        return `<td class="num">${c.type === "money" ? inr.format(sum) : num.format(sum)}</td>`;
      }
      return "<td></td>";
    }).join("")}</tr>`;
  }
  return `<p class="count">${rows.length}${rows.length >= 200 ? "+ (first 200 shown)" : ""} record${rows.length === 1 ? "" : "s"}</p>
    <div class="table-wrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body}${foot}</tbody></table></div>`;
}

const loading = (title) => { app.innerHTML = `${crumb()}<h1>${esc(title)}</h1><div class="loading">Loading from Snowflake…</div>`; };
const crumb = (extra = "") => `<div class="crumb"><a href="#/">Home</a>${extra ? " › " + extra : ""}</div>`;
const showError = (err, title = "Something went wrong") => {
  app.insertAdjacentHTML("beforeend", `<div class="error"><b>${esc(title)}:</b> ${esc(err.message || err)}</div>`);
};
const customerName = () => {
  const c = state.customers.find(x => x.SOLD_TO === state.customer);
  return c ? c.SOLD_TO_NAME : "all accounts";
};

/* ---------- column sets ---------- */
const orderCols = [
  { key: "SALES_DOC", label: "Order #", type: "link", href: r => `#/order/${r.SALES_DOC}` },
  { key: "DOC_DATE", label: "Order date" },
  { key: "CUSTOMER_PO", label: "PO #" },
  { key: "SOLD_TO_NAME", label: "Customer" },
  { key: "SHIP_TO_CITY", label: "Ship-to city" },
  { key: "ITEM_COUNT", label: "Items", type: "num" },
  { key: "NET_VALUE", label: "Net value", type: "money" },
  { key: "REQ_DELIVERY_DATE", label: "Requested" },
  { key: "OVERALL_STATUS_TEXT", label: "Status", type: "status", code: "OVERALL_STATUS" },
  { key: "DELIVERY_STATUS_TEXT", label: "Delivery" },
  { key: "BILLING_STATUS_TEXT", label: "Billing" },
  { key: "IS_CREDIT_BLOCKED", label: "Credit block", type: "bool", bad: true, yes: "Blocked" },
  { key: "CREATED_BY", label: "Created by" },
];

const deliveryCols = [
  { key: "DELIVERY_DOC", label: "Delivery #", type: "link", href: r => `#/delivery/${r.DELIVERY_DOC}` },
  { key: "DELIVERY_TYPE_TEXT", label: "Type" },
  { key: "SALES_DOC", label: "Order #", type: "link", href: r => `#/order/${r.SALES_DOC}` },
  { key: "CUSTOMER_PO", label: "PO #" },
  { key: "SHIP_TO_NAME", label: "Ship-to" },
  { key: "SHIP_TO_CITY", label: "City" },
  { key: "PLANT", label: "Plant" },
  { key: "CREATED_ON", label: "Created" },
  { key: "PLANNED_GOODS_ISSUE_DATE", label: "Planned ship" },
  { key: "ACTUAL_GOODS_ISSUE_DATE", label: "Shipped on" },
  { key: "ITEMS", label: "Items", type: "num" },
  { key: "GROSS_WEIGHT", label: "Weight (kg)", type: "num" },
  { key: "NET_VALUE", label: "Value", type: "money" },
  { key: "GOODS_MOVEMENT_STATUS_TEXT", label: "Goods issue" },
  { key: "INVOICE_DOC", label: "Invoice #", type: "doc" },
  { key: "IS_SHIPPED_NOT_BILLED", label: "Not invoiced", type: "bool", yes: "Not invoiced" },
];

/* ---------- views ---------- */
async function viewHome() {
  app.innerHTML = $("#tpl-home").innerHTML;
  wireQuickCart();
  $("#doc-search").addEventListener("submit", e => {
    e.preventDefault();
    location.hash = `#/search/${$("#doc-type").value}/${encodeURIComponent($("#doc-value").value.trim())}`;
  });
  try {
    const s = await api("/api/summary" + qs({ customer: state.customer }));
    $("#tiles").innerHTML = `
      <a class="tile" href="#/orders/open"><div class="k">Open orders</div><div class="v">${num.format(s.OPEN_ORDERS || 0)}</div></a>
      <a class="tile" href="#/orders/open"><div class="k">Open order value</div><div class="v">${inr.format(s.OPEN_ORDER_VALUE || 0)}</div></a>
      <a class="tile" href="#/orders/quick"><div class="k">Orders, last 30 days</div><div class="v">${num.format(s.ORDERS_LAST_30_DAYS || 0)}</div></a>
      <a class="tile warn" href="#/deliveries/not_billed"><div class="k">Shipped, not invoiced</div><div class="v">${inr.format(s.SHIPPED_NOT_BILLED_VALUE || 0)}</div></a>
      <a class="tile ${s.CREDIT_BLOCKED ? "bad" : ""}" href="#/orders/blocked"><div class="k">Credit-blocked orders</div><div class="v">${num.format(s.CREDIT_BLOCKED || 0)}</div></a>`;
  } catch (err) {
    $("#tiles").innerHTML = `<div class="error" style="grid-column: 1 / -1"><b>Snowflake not reachable:</b> ${esc(err.message)}</div>`;
  }
}

const ORDER_VIEWS = {
  quick: { title: "Quick Order Search", sub: "Open orders placed in the last 30 days", params: { view: "quick" } },
  recent: { title: "Recent Order Search", sub: "Filter by status, dates and who created the order", params: { view: "all" }, filters: true },
  manage: { title: "Manage Orders", sub: "Your open and closed orders", params: { view: "open" }, toggle: true },
  open: { title: "Open Orders", sub: "Orders not yet completed", params: { view: "open" } },
  blocked: { title: "Credit-Blocked Orders", sub: "Orders on credit hold", params: { view: "all", blocked: "true" } },
};

async function viewOrders(kind) {
  const cfg = ORDER_VIEWS[kind] || ORDER_VIEWS.recent;
  const f = Object.fromEntries(new URLSearchParams(location.hash.split("?")[1] || ""));
  app.innerHTML = `${crumb(esc(cfg.title))}<h1>${esc(cfg.title)} <small style="color:var(--muted);font-weight:400">· ${esc(customerName())}</small></h1>
    <p class="hint">${esc(cfg.sub)}</p>
    ${cfg.filters ? `
    <form class="filters" id="order-filters">
      <label>Status<select name="status"><option value="">Any</option><option value="A">Open</option><option value="B">In process</option><option value="C">Completed</option></select></label>
      <label>From<input type="date" name="date_from"></label>
      <label>To<input type="date" name="date_to"></label>
      <label>Created by<input name="created_by" placeholder="e.g. WEB_PORTAL"></label>
      <label>Order / PO / customer<input name="q"></label>
      <button type="submit">Apply</button>
    </form>` : ""}
    ${cfg.toggle ? `<div class="filters"><button class="btn ${f.view === "closed" ? "ghost" : ""}" data-v="open">Open orders</button>
      <button class="btn ${f.view === "closed" ? "" : "ghost"}" data-v="closed">Closed orders</button></div>` : ""}
    ${askBanner("orders")}
    <div id="result"><div class="loading">Loading from Snowflake…</div></div>`;
  wireAskBanner();
  const form = $("#order-filters");
  if (form) {
    Object.entries(f).forEach(([k, v]) => { if (form.elements[k]) form.elements[k].value = v; });
    form.addEventListener("submit", e => {
      e.preventDefault();
      location.hash = `#/orders/${kind}` + qs(Object.fromEntries(new FormData(form)));
    });
  }
  app.querySelectorAll("[data-v]").forEach(b => b.addEventListener("click", () => { location.hash = `#/orders/${kind}?view=${b.dataset.v}`; }));
  try {
    const rows = await api("/api/orders" + qs({ ...cfg.params, ...f, customer: state.customer }));
    $("#result").innerHTML = table(rows, orderCols, { totals: ["NET_VALUE", "ITEM_COUNT"] });
  } catch (err) { $("#result").innerHTML = ""; showError(err); }
}

async function viewSearch(type, value) {
  const label = { order: "Order #", po: "PO #", delivery: "Delivery #", invoice: "Invoice #" }[type] || type;
  loading(`Search: ${label} ${value}`);
  try {
    const rows = await api("/api/search" + qs({ type, value, customer: state.customer }));
    if (rows.length === 1 && type !== "po") { location.replace(`#/order/${rows[0].SALES_DOC}`); return; }
    app.innerHTML = `${crumb("Search")}<h1>${esc(label)} “${esc(value)}”</h1>${table(rows, orderCols, { empty: `No sales document found for ${label} ${value} in ${customerName()}.` })}`;
  } catch (err) { showError(err); }
}

async function viewOrder(doc) {
  loading(`Order ${strip0(doc)}`);
  try {
    const d = await api(`/api/orders/${encodeURIComponent(doc)}`);
    const h = d.header;
    const f = (label, v) => `<div><span>${esc(label)}</span><b>${v}</b></div>`;
    app.innerHTML = `${crumb(`<a href="#/orders/recent">Orders</a> › ${esc(strip0(h.SALES_DOC))}`)}
      <h1>${esc(h.DOC_CATEGORY_TEXT)} ${esc(strip0(h.SALES_DOC))} <span class="chip ${esc(h.OVERALL_STATUS)}">${esc(h.OVERALL_STATUS_TEXT)}</span>
        ${h.IS_CREDIT_BLOCKED ? '<span class="chip bad">Credit block</span>' : ""}</h1>
      <div class="panel detail-head">
        ${f("Customer", esc(h.SOLD_TO_NAME) + " (" + esc(strip0(h.SOLD_TO)) + ")")}
        ${f("Ship-to", esc(h.SHIP_TO_NAME || "") + ", " + esc(h.SHIP_TO_CITY || ""))}
        ${f("PO #", esc(h.CUSTOMER_PO || ""))}
        ${f("Document type", esc(h.DOC_TYPE_TEXT || h.DOC_TYPE))}
        ${f("Order date", esc(h.DOC_DATE))}
        ${f("Requested delivery", esc(h.REQ_DELIVERY_DATE || ""))}
        ${f("Payment terms", esc(h.PAYMENT_TERMS || ""))}
        ${f("Incoterms", esc((h.INCOTERMS || "") + " " + (h.INCOTERMS_LOCATION || "")))}
        ${f("Net value", inr.format(h.NET_VALUE || 0))}
        ${f("GST", inr.format(h.TAX_VALUE || 0))}
        ${f("Total incl. GST", inr.format(h.GROSS_VALUE || 0))}
        ${f("Invoiced (net)", inr.format(h.NET_BILLED_VALUE || 0))}
        ${f("Delivery status", esc(h.DELIVERY_STATUS_TEXT))}
        ${f("Billing status", esc(h.BILLING_STATUS_TEXT))}
        ${f("Created by", esc(h.CREATED_BY || ""))}
        ${f("Loaded into Snowflake", esc(String(h.LAST_LOADED_AT || "").replace("T", " ").slice(0, 19)))}
      </div>
      <h2 class="section-title">Items</h2>
      ${table(d.items, [
        { key: "ITEM", label: "Item", type: "doc" },
        { key: "MATERIAL", label: "Part number" },
        { key: "MATERIAL_TEXT", label: "Description" },
        { key: "ORDER_QTY", label: "Ordered", type: "num" },
        { key: "SALES_UNIT", label: "Unit" },
        { key: "CONFIRMED_QTY", label: "Confirmed", type: "num" },
        { key: "DELIVERED_QTY", label: "Delivered", type: "num" },
        { key: "OPEN_DELIVERY_QTY", label: "Open", type: "num" },
        { key: "LIST_PRICE", label: "List price", type: "money" },
        { key: "DISCOUNT_VALUE", label: "Discount", type: "money" },
        { key: "NET_VALUE", label: "Net value", type: "money" },
        { key: "TAX_VALUE", label: "GST", type: "money" },
        { key: "LAST_CONFIRMED_DATE", label: "Confirmed date" },
        { key: "DELIVERY_STATUS_TEXT", label: "Delivery" },
        { key: "IS_REJECTED", label: "Rejected", type: "bool", bad: true, yes: "Rejected" },
        { key: "HAS_BACKORDER", label: "Backorder", type: "bool", yes: "Backorder" },
      ], { totals: ["NET_VALUE", "TAX_VALUE"] })}
      <h2 class="section-title">Deliveries</h2>
      ${table(d.deliveries, [
        { key: "DELIVERY_DOC", label: "Delivery #", type: "link", href: r => `#/delivery/${r.DELIVERY_DOC}` },
        { key: "SALES_ITEM", label: "Order item", type: "doc" },
        { key: "MATERIAL_TEXT", label: "Description" },
        { key: "DELIVERY_QTY", label: "Qty", type: "num" },
        { key: "PLANNED_GOODS_ISSUE_DATE", label: "Planned ship" },
        { key: "ACTUAL_GOODS_ISSUE_DATE", label: "Shipped on" },
        { key: "GOODS_MOVEMENT_STATUS_TEXT", label: "Goods issue" },
        { key: "BILLING_STATUS_TEXT", label: "Billing" },
        { key: "INVOICE_DOC", label: "Invoice #", type: "doc" },
      ], { empty: "No deliveries yet." })}`;
  } catch (err) {
    app.innerHTML = crumb("Order");
    showError(err, "Order not available");
    app.insertAdjacentHTML("beforeend", `<p class="hint">Orders placed in the last few minutes reach Snowflake through CDC in about 2–3 minutes.</p>`);
  }
}

async function viewDeliveries(status = "all") {
  const f = Object.fromEntries(new URLSearchParams(location.hash.split("?")[1] || ""));
  app.innerHTML = `${crumb("Delivery Search")}<h1>Delivery Search <small style="color:var(--muted);font-weight:400">· ${esc(customerName())}</small></h1>
    <form class="filters" id="del-filters">
      <label>Show<select name="status">
        <option value="all">All deliveries</option><option value="in_process">In process (not shipped)</option>
        <option value="shipped">Shipped</option><option value="not_billed">Shipped, not invoiced</option></select></label>
      <label>From<input type="date" name="date_from"></label>
      <label>To<input type="date" name="date_to"></label>
      <label>Delivery / order / PO #<input name="q"></label>
      <button type="submit">Search</button>
    </form><div id="result"><div class="loading">Loading from Snowflake…</div></div>`;
  const form = $("#del-filters");
  form.elements.status.value = status;
  Object.entries(f).forEach(([k, v]) => { if (form.elements[k]) form.elements[k].value = v; });
  form.addEventListener("submit", e => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    const st = data.status; delete data.status;
    location.hash = `#/deliveries/${st}` + qs(data);
  });
  try {
    const rows = await api("/api/deliveries" + qs({ ...f, status, customer: state.customer }));
    $("#result").innerHTML = table(rows, deliveryCols, { totals: ["NET_VALUE"] });
  } catch (err) { $("#result").innerHTML = ""; showError(err); }
}

async function viewDelivery(doc) {
  loading(`Delivery ${strip0(doc)}`);
  try {
    const d = await api(`/api/deliveries/${encodeURIComponent(doc)}`);
    const h = d.header;
    const f = (label, v) => `<div><span>${esc(label)}</span><b>${esc(v ?? "")}</b></div>`;
    app.innerHTML = `${crumb(`<a href="#/deliveries">Deliveries</a> › ${esc(strip0(h.DELIVERY_DOC))}`)}
      <h1>${esc(h.DELIVERY_TYPE_TEXT || "Delivery")} ${esc(strip0(h.DELIVERY_DOC))}</h1>
      <div class="panel detail-head">
        ${f("Order #", strip0(h.SALES_DOC))} ${f("PO #", h.CUSTOMER_PO)} ${f("Customer", h.SOLD_TO_NAME)}
        ${f("Ship-to", `${h.SHIP_TO_NAME}, ${h.SHIP_TO_CITY} ${h.SHIP_TO_POSTAL_CODE || ""}`)}
        ${f("Plant / shipping point", `${h.PLANT} / ${h.SHIPPING_POINT}`)} ${f("Route", h.ROUTE)}
        ${f("Planned delivery", h.PLANNED_DELIVERY_DATE)} ${f("Planned ship", h.PLANNED_GOODS_ISSUE_DATE)}
        ${f("Shipped on", h.ACTUAL_GOODS_ISSUE_DATE || "Not shipped yet")} ${f("Picking", h.PICKING_STATUS_TEXT)}
        ${f("Goods issue", h.GOODS_MOVEMENT_STATUS_TEXT)} ${f("Billing", h.BILLING_STATUS_TEXT)}
        ${f("Packages", h.PACKAGES_IN_DELIVERY)} ${f("Incoterms", `${h.INCOTERMS || ""} ${h.INCOTERMS_LOCATION || ""}`)}
        ${f("Material document", strip0(h.MATERIAL_DOC))} ${f("Invoice #", strip0(h.INVOICE_DOC))}
      </div>
      <p><a href="#/order/${esc(h.SALES_DOC)}">Open sales order ${esc(strip0(h.SALES_DOC))}</a></p>
      ${table(d.items, [
        { key: "ITEM", label: "Item", type: "doc" },
        { key: "SALES_ITEM", label: "Order item", type: "doc" },
        { key: "MATERIAL", label: "Part number" },
        { key: "MATERIAL_TEXT", label: "Description" },
        { key: "DELIVERY_QTY", label: "Qty", type: "num" },
        { key: "SALES_UNIT", label: "Unit" },
        { key: "GROSS_WEIGHT", label: "Gross weight", type: "num" },
        { key: "DELIVERY_NET_VALUE", label: "Value", type: "money" },
      ], { totals: ["DELIVERY_QTY", "GROSS_WEIGHT", "DELIVERY_NET_VALUE"] })}`;
  } catch (err) { app.innerHTML = crumb("Delivery"); showError(err, "Delivery not available"); }
}

async function viewDocuments() {
  const f = Object.fromEntries(new URLSearchParams(location.hash.split("?")[1] || ""));
  app.innerHTML = `${crumb("Document Search")}<h1>Document Search <small style="color:var(--muted);font-weight:400">· ${esc(customerName())}</small></h1>
    <form class="filters" id="docs-filters">
      <label>Document type<select name="doc_type">
        <option value="all">All</option><option value="order">Sales orders</option><option value="quotation">Quotations</option>
        <option value="delivery">Deliveries</option><option value="invoice">Invoices</option><option value="return">Returns</option></select></label>
      <label>From<input type="date" name="date_from"></label>
      <label>To<input type="date" name="date_to"></label>
      <label>Document / order / PO #<input name="q"></label>
      <button type="submit">Search</button>
    </form><div id="result"><div class="loading">Loading from Snowflake…</div></div>`;
  const form = $("#docs-filters");
  Object.entries(f).forEach(([k, v]) => { if (form.elements[k]) form.elements[k].value = v; });
  form.addEventListener("submit", e => { e.preventDefault(); location.hash = "#/documents" + qs(Object.fromEntries(new FormData(form))); });
  try {
    const rows = await api("/api/documents" + qs({ ...f, customer: state.customer }));
    $("#result").innerHTML = table(rows, [
      { key: "DOC_TYPE", label: "Type" },
      { key: "DOCUMENT", label: "Document #", type: "link",
        href: r => r.DOC_TYPE.includes("elivery") ? `#/delivery/${r.DOCUMENT}` : r.DOC_TYPE === "Invoice" ? `#/order/${r.SALES_DOC}` : `#/order/${r.DOCUMENT}` },
      { key: "DOC_DATE", label: "Date" },
      { key: "SALES_DOC", label: "Order #", type: "link", href: r => `#/order/${r.SALES_DOC}` },
      { key: "CUSTOMER_PO", label: "PO #" },
      { key: "AMOUNT", label: "Amount (net)", type: "money" },
      { key: "STATUS", label: "Status" },
    ]);
  } catch (err) { $("#result").innerHTML = ""; showError(err); }
}

async function viewReturns() {
  loading("Return Center");
  try {
    const rows = await api("/api/returns" + qs({ customer: state.customer }));
    app.innerHTML = `${crumb("Return Center")}<h1>Return Center <small style="color:var(--muted);font-weight:400">· ${esc(customerName())}</small></h1>
      <p class="hint">Customer returns and their credit status.</p>
      ${table(rows, orderCols.filter(c => !["IS_CREDIT_BLOCKED"].includes(c.key)), { empty: "No returns for this account." })}`;
  } catch (err) { showError(err); }
}

async function viewProducts(query = "", category = "") {
  loading(category ? `Category ${category}` : query ? `Products matching “${query}”` : "Product catalogue");
  try {
    const rows = await api("/api/products" + qs({ q: query, category }));
    app.innerHTML = `${crumb("Products")}<h1>${category ? `Category: ${esc(category)}` : query ? `Products matching “${esc(query)}”` : "Product catalogue"}</h1>
      ${table(rows, [
        { key: "MATERIAL", label: "Part number" },
        { key: "MATERIAL_TEXT", label: "Description" },
        { key: "MATERIAL_GROUP", label: "Category" },
        { key: "SALES_UNIT", label: "Unit" },
        { key: "LIST_PRICE", label: "List price", type: "money" },
        { key: "TIMES_ORDERED", label: "Times ordered", type: "num" },
      ], { empty: "No products found." })}`;
    const tbl = app.querySelector("table.data");
    if (tbl) {
      tbl.querySelector("thead tr").insertAdjacentHTML("beforeend", "<th></th>");
      tbl.querySelectorAll("tbody tr").forEach((tr, i) => {
        tr.insertAdjacentHTML("beforeend", `<td><button class="btn green" data-i="${i}">Add to cart</button></td>`);
      });
      tbl.addEventListener("click", e => {
        const b = e.target.closest("button[data-i]");
        if (!b) return;
        const r = rows[Number(b.dataset.i)];
        addToCart([{ material: r.MATERIAL, qty: 1, description: r.MATERIAL_TEXT, list_price: r.LIST_PRICE }]);
      });
    }
  } catch (err) { showError(err); }
}

async function viewSummary() {
  location.hash = "#/";
}

/* ---------- quick cart, upload, paste ---------- */
function entryRow(n) {
  return `<tr><td>${n}</td><td><input list="parts" class="pn" placeholder="Part number"></td>
    <td><input type="number" min="1" step="1" class="qty"></td><td><input type="date" class="rd"></td></tr>`;
}

async function wireQuickCart() {
  const rows = $("#entry-rows");
  rows.innerHTML = [1, 2, 3].map(entryRow).join("");
  $("#add-rows").addEventListener("click", e => {
    e.preventDefault();
    const n = rows.children.length;
    rows.insertAdjacentHTML("beforeend", [1, 2, 3].map(i => entryRow(n + i)).join(""));
  });
  app.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
    app.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === t));
    app.querySelectorAll(".tab-body").forEach(b => b.classList.toggle("hidden", b.dataset.body !== t.dataset.tab));
    $("#add-rows").classList.toggle("hidden", t.dataset.tab !== "quick");
  }));
  $("#add-cart").addEventListener("click", async () => {
    const lines = await readEntryLines();
    if (lines.length) addToCart(lines);
  });
  $("#check-avail").addEventListener("click", async () => {
    const lines = await readEntryLines();
    if (lines.length) checkAvailability(lines, $("#avail-result"));
  });
  try {
    const products = await api("/api/products");
    $("#parts").innerHTML = products.map(p => `<option value="${esc(p.MATERIAL)}">${esc(p.MATERIAL_TEXT)}</option>`).join("");
  } catch { /* datalist is optional */ }
}

function parseLines(text) {
  return text.split(/\r?\n/).map(l => l.trim()).filter(l => l && !/^part/i.test(l)).map(l => {
    const [material, qty, date] = l.split(/[,\t;]/).map(x => (x || "").trim());
    return { material, qty: Number(qty), requested_date: date || null };
  });
}

async function readEntryLines() {
  const active = app.querySelector(".tab.active").dataset.tab;
  let lines = [];
  if (active === "quick") {
    lines = [...$("#entry-rows").children].map(tr => ({
      material: tr.querySelector(".pn").value.trim(),
      qty: Number(tr.querySelector(".qty").value),
      requested_date: tr.querySelector(".rd").value || null,
    })).filter(l => l.material || l.qty);
  } else if (active === "paste") {
    lines = parseLines($("#paste-box").value);
  } else {
    const file = $("#upload-file").files[0];
    if (!file) { toast("Choose a CSV file first."); return []; }
    lines = parseLines(await file.text());
  }
  const bad = lines.filter(l => !l.material || !(l.qty > 0) || (l.requested_date && !/^\d{4}-\d{2}-\d{2}$/.test(l.requested_date)));
  if (bad.length) { toast(`Check ${bad.length} line(s): each needs a part number, a quantity above 0 and an optional YYYY-MM-DD date.`); return []; }
  if (!lines.length) toast("Enter at least one part number and quantity.");
  return lines;
}

async function checkAvailability(lines, target) {
  target.innerHTML = `<div class="loading">Checking availability in Snowflake…</div>`;
  try {
    const res = await api("/api/availability", { method: "POST", body: JSON.stringify({ lines: lines.map(({ material, qty, requested_date }) => ({ material, qty, requested_date })) }) });
    const rows = res.lines.map(l => ({
      ...l,
      result: !l.found ? "Not found" : !l.orderable ? "Not orderable online" : l.meets_requested_date === false ? "Later than requested" : "Available to order",
      result_code: !l.found || !l.orderable ? "bad" : l.meets_requested_date === false ? "warn" : "ok",
    }));
    target.innerHTML = `<h2 class="section-title">Availability</h2>${table(rows, [
      { key: "material", label: "Part number" },
      { key: "description", label: "Description" },
      { key: "qty", label: "Qty", type: "num" },
      { key: "list_price", label: "List price", type: "money" },
      { key: "line_value", label: "Value at list price", type: "money" },
      { key: "requested_date", label: "Requested" },
      { key: "estimated_ship_date", label: "Est. ship date" },
      { key: "result", label: "Result", type: "status", code: "result_code" },
      { key: "open_backlog_qty", label: "Open backlog qty", type: "num" },
    ], { totals: ["line_value"] })}<p class="hint">${esc(res.note)} Lead time basis per line: ${rows.filter(r => r.found).map(r => `${esc(r.material)} ${r.lead_days} days (${esc(r.lead_basis)})`).join("; ")}.</p>`;
    return res;
  } catch (err) { target.innerHTML = `<div class="error">${esc(err.message)}</div>`; return null; }
}

/* ---------- cart ---------- */
function saveCart() {
  store.set("cart", state.cart);
  $("#cart-count").textContent = `(${state.cart.length})`;
}

function addToCart(lines) {
  lines.forEach(l => {
    const existing = state.cart.find(c => c.material.toUpperCase() === l.material.toUpperCase());
    if (existing) existing.qty += l.qty;
    else state.cart.push({ material: l.material, qty: l.qty, requested_date: l.requested_date || null, description: l.description || "" });
  });
  saveCart();
  toast(`${lines.length} line(s) added to cart.`);
}

function viewCart() {
  const rows = state.cart.map((c, i) => `<tr>
      <td>${esc(c.material)}</td><td>${esc(c.description || "")}</td>
      <td><input type="number" min="1" value="${esc(c.qty)}" data-i="${i}" class="cart-qty" style="width:90px"></td>
      <td><input type="date" value="${esc(c.requested_date || "")}" data-i="${i}" class="cart-date"></td>
      <td><a href="#" data-remove="${i}">Remove</a></td></tr>`).join("");
  app.innerHTML = `${crumb("Cart")}<h1>Cart <small style="color:var(--muted);font-weight:400">· ordering for ${esc(customerName())}</small></h1>
    ${state.cart.length ? `
      <div class="table-wrap"><table class="data"><thead><tr><th>Part number</th><th>Description</th><th>Quantity</th><th>Requested ship by</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <div class="filters" style="margin-top:14px">
        <label>Your PO number<input id="po" maxlength="35" placeholder="e.g. PO/4711" required></label>
        <button class="btn green outline" id="cart-check">Check Availability</button>
        <button class="btn green" id="place" ${state.oracle ? "" : "disabled title='Order entry is disabled on the server'"}>Place Order</button>
        <a href="#" id="clear-cart">Empty cart</a>
      </div>
      <div id="cart-result"></div>` : `<div class="table-wrap"><div class="empty">Your cart is empty. Use Quick Cart on the home page or the product search.</div></div>`}`;
  if (!state.cart.length) return;
  app.querySelectorAll(".cart-qty").forEach(inp => inp.addEventListener("change", () => { state.cart[inp.dataset.i].qty = Number(inp.value) || 1; saveCart(); }));
  app.querySelectorAll(".cart-date").forEach(inp => inp.addEventListener("change", () => { state.cart[inp.dataset.i].requested_date = inp.value || null; saveCart(); }));
  app.querySelectorAll("[data-remove]").forEach(a => a.addEventListener("click", e => { e.preventDefault(); state.cart.splice(Number(a.dataset.remove), 1); saveCart(); viewCart(); }));
  $("#clear-cart").addEventListener("click", e => { e.preventDefault(); state.cart = []; saveCart(); viewCart(); });
  $("#cart-check").addEventListener("click", () => checkAvailability(state.cart, $("#cart-result")));
  $("#place").addEventListener("click", placeOrder);
}

async function placeOrder() {
  if (!state.customer) { toast("Choose a customer under “Shopping for” before placing an order."); return; }
  const po = $("#po").value.trim();
  if (!po) { toast("Enter your PO number."); $("#po").focus(); return; }
  const btn = $("#place");
  btn.disabled = true; btn.textContent = "Placing order…";
  try {
    const res = await api("/api/orders", { method: "POST", body: JSON.stringify({
      customer: state.customer, customer_po: po,
      lines: state.cart.map(({ material, qty, requested_date }) => ({ material, qty, requested_date })) }) });
    state.cart = []; saveCart();
    const started = Date.now();
    app.innerHTML = `${crumb("Order placed")}<h1>Thank you, order ${esc(strip0(res.sales_doc))} has been placed</h1>
      <div class="panel detail-head">
        <div><span>Order #</span><b>${esc(strip0(res.sales_doc))}</b></div>
        <div><span>PO #</span><b>${esc(res.customer_po)}</b></div>
        <div><span>Items</span><b>${res.items}</b></div>
        <div><span>Requested delivery</span><b>${esc(res.requested_delivery_date)}</b></div>
        <div><span>Net value</span><b>${inr.format(res.net_value)}</b></div>
        <div><span>GST</span><b>${inr.format(res.tax_value)}</b></div>
        <div><span>Total</span><b>${inr.format(res.net_value + res.tax_value)}</b></div>
      </div>
      <p>${esc(res.message)}</p>
      <p id="cdc-status" class="hint">Waiting for the order to arrive in Snowflake… (checking every 15 seconds)</p>`;
    const poll = async () => {
      if (!location.hash.startsWith("#/cart")) return;
      try {
        await api(`/api/orders/${res.sales_doc}`);
        const secs = Math.round((Date.now() - started) / 1000);
        $("#cdc-status").innerHTML = `&#10003; Arrived in Snowflake Gold after ${secs} seconds. <a href="#/order/${esc(res.sales_doc)}">View order ${esc(strip0(res.sales_doc))}</a>`;
      } catch {
        if (Date.now() - started < 10 * 60 * 1000) setTimeout(poll, 15000);
        else $("#cdc-status").textContent = "Not visible after 10 minutes - check the connectors (scripts/status.sh) and Snowflake tasks.";
      }
    };
    setTimeout(poll, 15000);
  } catch (err) {
    btn.disabled = false; btn.textContent = "Place Order";
    $("#cart-result").innerHTML = `<div class="error"><b>Order not placed:</b> ${esc(err.message)}</div>`;
  }
}

/* ---------- header: accounts, categories, product search ---------- */
async function loadHeader() {
  const sel = $("#account");
  try {
    const health = await api("/api/health");
    state.oracle = !!health.oracle_orders_enabled;
    $("#freshness").textContent = `Data as of ${String(health.DATA_AS_OF || "").replace("T", " ").slice(0, 19)} · role ${health.ROLE} · warehouse ${health.WAREHOUSE}`;
  } catch (err) {
    $("#freshness").textContent = `Snowflake not reachable: ${err.message}`;
  }
  try {
    state.customers = await api("/api/customers");
    sel.innerHTML = `<option value="">All accounts (CSR view)</option>` +
      state.customers.map(c => `<option value="${esc(c.SOLD_TO)}">${esc(c.SOLD_TO_NAME)} – #${esc(strip0(c.SOLD_TO))}</option>`).join("");
    if (!state.customers.some(c => c.SOLD_TO === state.customer)) state.customer = "";
    sel.value = state.customer;
    updateAccountMeta();
  } catch { sel.innerHTML = `<option value="">(customers unavailable)</option>`; }
  sel.addEventListener("change", () => { state.customer = sel.value; store.set("customer", state.customer); updateAccountMeta(); route(); });
  try {
    const cats = await api("/api/categories");
    $("#category-list").innerHTML = cats.map(c =>
      `<a href="#/category/${encodeURIComponent(c.MATERIAL_GROUP)}">${esc(c.MATERIAL_GROUP)} <span>${c.PRODUCTS}</span></a>`).join("");
  } catch { /* optional */ }
  $("#product-search").addEventListener("submit", e => {
    e.preventDefault();
    location.hash = `#/products/${encodeURIComponent($("#product-q").value.trim())}`;
  });
  document.addEventListener("click", e => {          // close dropdowns after a choice
    if (e.target.closest(".dropdown a")) document.querySelectorAll("details[open]").forEach(d => d.removeAttribute("open"));
  });
}

function updateAccountMeta() {
  const c = state.customers.find(x => x.SOLD_TO === state.customer);
  $("#account-meta").textContent = c ? `Account # ${strip0(c.SOLD_TO)} · ${c.SOLD_TO_CITY} · ${c.DISTR_CHANNEL === "20" ? "Distributor" : "Direct"}` : "Customer service view of every account";
}

/* ---------- router ---------- */
function route() {
  const [path] = location.hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  window.scrollTo(0, 0);
  switch (parts[0]) {
    case undefined: return viewHome();
    case "orders": return viewOrders(parts[1] || "recent");
    case "order": return viewOrder(parts[1]);
    case "search": return viewSearch(parts[1], parts[2] || "");
    case "deliveries": return viewDeliveries(parts[1] || "all");
    case "delivery": return viewDelivery(parts[1]);
    case "documents": return viewDocuments();
    case "returns": return viewReturns();
    case "products": return viewProducts(parts[1] || "");
    case "category": return viewProducts("", parts[1] || "");
    case "cart": return viewCart();
    case "summary": return viewSummary();
    default: return viewHome();
  }
}

/* ---------- AI assistant (Snowflake Cortex Agent) ---------- */
const ai = { history: [], busy: false };

const SUGGESTIONS = {
  orders: ["Which orders are still open, and what is their value?", "Show orders created in the last 7 days",
           "Which open orders are past the requested delivery date?", "Top 5 customers by order value this month"],
  deliveries: ["Which deliveries are shipped but not invoiced?", "What is our on-time shipping % by plant?"],
  home: ["Summarise this account's orders, deliveries and invoices", "What is the open backlog by product?",
         "Which orders are blocked for credit?", "Billed revenue and margin by month"],
};

function pageKind() {
  const p = location.hash.replace(/^#\//, "").split(/[/?]/)[0];
  return p.startsWith("deliver") ? "deliveries" : p.startsWith("order") || p === "search" ? "orders" : "home";
}

function askBanner(kind) {
  return `<div class="ask-banner"><b>&#10024; Ask about these orders:</b>
    ${SUGGESTIONS[kind].slice(0, 3).map(q => `<button type="button" data-ask="${esc(q)}">${esc(q)}</button>`).join("")}</div>`;
}

function wireAskBanner() {
  app.querySelectorAll("[data-ask]").forEach(b => b.addEventListener("click", () => { openAssistant(); askAgent(b.dataset.ask); }));
}

function mdLite(text) {
  // Minimal, safe formatting: escape first, then **bold**, `code`, bullet lists, paragraphs.
  const lines = esc(text).split(/\n/);
  let html = "", inList = false;
  for (const raw of lines) {
    const line = raw.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
    const bullet = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)/);
    if (bullet) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${bullet[1]}</li>`; continue; }
    if (inList) { html += "</ul>"; inList = false; }
    if (line.trim()) html += `<p>${line}</p>`;
  }
  return html + (inList ? "</ul>" : "");
}

function agentTable(t) {
  const isNum = v => v !== null && v !== "" && !isNaN(Number(v)) && !/^0\d/.test(String(v));
  const head = t.columns.map(c => `<th>${esc(c)}</th>`).join("");
  const body = t.rows.map(r => `<tr>${r.map(v => `<td class="${isNum(v) ? "num" : ""}">${
    v === null ? "" : isNum(v) && String(v).includes(".") ? num.format(Number(v)) : esc(strip0(v))}</td>`).join("")}</tr>`).join("");
  return `${t.title ? `<div class="count">${esc(t.title)}</div>` : ""}<div class="table-wrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
    ${t.row_count > t.rows.length ? `<div class="count">First ${t.rows.length} of ${t.row_count} rows</div>` : ""}`;
}

function addMsg(cls, html) {
  const log = $("#ai-log");
  log.insertAdjacentHTML("beforeend", `<div class="msg ${cls}">${html}</div>`);
  log.scrollTop = log.scrollHeight;
  return log.lastElementChild;
}

function renderSuggestions() {
  $("#ai-suggest").innerHTML = SUGGESTIONS[pageKind()].map(q => `<button type="button">${esc(q)}</button>`).join("");
  $("#ai-suggest").querySelectorAll("button").forEach(b => b.addEventListener("click", () => askAgent(b.textContent)));
  $("#ai-scope").textContent = state.customer ? `Answering for ${customerName()}` : "All accounts";
}

function openAssistant() {
  $("#ai-panel").classList.remove("hidden");
  $("#ai-open").classList.add("hidden");
  renderSuggestions();
  if (!$("#ai-log").children.length) {
    addMsg("bot", mdLite("Hi! I can answer questions about orders, items, deliveries, invoices and backlog using live SAP data in Snowflake. " +
      (state.customer ? `I'll focus on **${customerName()}**; switch to *All accounts* at the top to ask about everyone.` : "")));
  }
  $("#ai-input").focus();
}

function closeAssistant() {
  $("#ai-panel").classList.add("hidden");
  $("#ai-open").classList.remove("hidden");
}

async function askAgent(question) {
  question = (question || "").trim();
  if (!question || ai.busy) return;
  ai.busy = true;
  $("#ai-send").disabled = true;
  addMsg("user", esc(question));
  const pending = addMsg("bot", `<span class="typing">Thinking… querying Snowflake</span>`);
  try {
    const res = await api("/api/agent", { method: "POST", body: JSON.stringify({
      question, customer: state.customer || null, page: location.hash, history: ai.history.slice(-10) }) });
    let html = res.answer ? mdLite(res.answer) : "<p>(No text answer returned.)</p>";
    res.tables.forEach(t => { html += agentTable(t); });
    if (res.sql.length) html += `<details><summary>SQL used (${res.sql.length})</summary>${res.sql.map(q => `<pre>${esc(q)}</pre>`).join("")}</details>`;
    if (res.warnings.length) html += `<div class="warn-note">${res.warnings.map(esc).join("<br>")}</div>`;
    pending.innerHTML = html;
    ai.history.push({ role: "user", text: question }, { role: "assistant", text: res.answer || "" });
  } catch (err) {
    pending.classList.add("err");
    pending.innerHTML = `<b>Assistant unavailable:</b> ${esc(err.message)}`;
  } finally {
    ai.busy = false;
    $("#ai-send").disabled = false;
    $("#ai-log").scrollTop = $("#ai-log").scrollHeight;
  }
}

$("#ai-open").addEventListener("click", openAssistant);
$("#ai-close").addEventListener("click", closeAssistant);
$("#ai-clear").addEventListener("click", () => { ai.history = []; $("#ai-log").innerHTML = ""; openAssistant(); });
$("#ai-form").addEventListener("submit", e => { e.preventDefault(); const q = $("#ai-input").value; $("#ai-input").value = ""; askAgent(q); });
$("#ai-input").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ai-form").requestSubmit(); }
});
window.addEventListener("hashchange", () => { if (!$("#ai-panel").classList.contains("hidden")) renderSuggestions(); });
$("#account").addEventListener("change", () => { if (!$("#ai-panel").classList.contains("hidden")) renderSuggestions(); });

window.addEventListener("hashchange", route);
saveCart();
loadHeader().then(route);
