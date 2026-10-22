"""
Generates consistent sample data for the S/4HANA SD tables in s4_sd_oracle_ddl.sql
and writes it as an Oracle INSERT script (s4_sd_sample_data.sql).

Scenarios covered (all linked through VBFA document flow):
  - Standard orders -> delivery -> goods issue -> invoice (F2)
  - Order with a rejected item
  - Partial delivery with two schedule lines (back-order)
  - Delivered + goods issued but not yet billed
  - Picked but not goods issued
  - Credit-blocked order
  - Open (unprocessed) orders
  - Quotation converted to order, plus one open quotation
  - Invoice cancelled (S1) and re-billed  -> the "never count twice" trap
  - Service order billed order-related (F1)
  - Customer return (RE) -> returns delivery (LR) -> credit memo (RE)
  - Distributor channel discount (K004) and Indian GST (CGST+SGST vs IGST)

Change SEED / N_ORDERS to generate a different or larger data set.
"""
import random
import datetime as dt
from collections import defaultdict

SEED = 2026
N_ORDERS = 24
OUT = "s4_sd_sample_data.sql"
random.seed(SEED)
D = dt.date

TABLES = [
    "T001", "T001W", "TVKO", "TVTW", "TSPA", "TVTA", "TVAK", "TVLK", "TVFK",
    "BUT000", "CVI_CUST_LINK", "KNA1", "KNB1", "KNVV", "KNVP",
    "MARA", "MAKT", "MARC", "MVKE",
    "VBAK", "VBAP", "VBEP", "VBKD", "VBPA",
    "LIKP", "LIPS", "VBRK", "VBRP", "VBFA", "PRCD_ELEMENTS",
]
PKS = {
    "T001": ["MANDT", "BUKRS"], "T001W": ["MANDT", "WERKS"], "TVKO": ["MANDT", "VKORG"],
    "TVTW": ["MANDT", "VTWEG"], "TSPA": ["MANDT", "SPART"],
    "TVTA": ["MANDT", "VKORG", "VTWEG", "SPART"], "TVAK": ["MANDT", "AUART"],
    "TVLK": ["MANDT", "LFART"], "TVFK": ["MANDT", "FKART"],
    "BUT000": ["CLIENT", "PARTNER"], "CVI_CUST_LINK": ["CLIENT", "PARTNER_GUID"],
    "KNA1": ["MANDT", "KUNNR"], "KNB1": ["MANDT", "KUNNR", "BUKRS"],
    "KNVV": ["MANDT", "KUNNR", "VKORG", "VTWEG", "SPART"],
    "KNVP": ["MANDT", "KUNNR", "VKORG", "VTWEG", "SPART", "PARVW", "PARZA"],
    "MARA": ["MANDT", "MATNR"], "MAKT": ["MANDT", "MATNR", "SPRAS"],
    "MARC": ["MANDT", "MATNR", "WERKS"], "MVKE": ["MANDT", "MATNR", "VKORG", "VTWEG"],
    "PRCD_ELEMENTS": ["CLIENT", "KNUMV", "KPOSN", "STUNR", "ZAEHK"],
    "VBAK": ["MANDT", "VBELN"], "VBAP": ["MANDT", "VBELN", "POSNR"],
    "VBEP": ["MANDT", "VBELN", "POSNR", "ETENR"], "VBKD": ["MANDT", "VBELN", "POSNR"],
    "VBPA": ["MANDT", "VBELN", "POSNR", "PARVW"], "VBFA": ["MANDT", "RUUID"],
    "LIKP": ["MANDT", "VBELN"], "LIPS": ["MANDT", "VBELN", "POSNR"],
    "VBRK": ["MANDT", "VBELN"], "VBRP": ["MANDT", "VBELN", "POSNR"],
}
rows = {t: [] for t in TABLES}


class Raw(str):
    """Marks a hex string that must be written as HEXTORAW(...)."""


def add(table, **cols):
    client_col = "CLIENT" if table in ("BUT000", "CVI_CUST_LINK", "PRCD_ELEMENTS") else "MANDT"
    rows[table].append({client_col: "100", **{k.upper(): v for k, v in cols.items()}})


def tm(lo=9, hi=19):
    return f"{random.randint(lo, hi - 1):02d}{random.randint(0, 59):02d}{random.randint(0, 59):02d}"


def guid():
    return Raw("%032X" % random.getrandbits(128))


class Seq:
    def __init__(self, start, width=10):
        self.n, self.w = start, width

    def next(self):
        v = str(self.n).zfill(self.w)
        self.n += 1
        return v


def posnr(i):
    return str(i * 10).zfill(6)


def fiscal(d):  # Indian fiscal year variant V3 (April-March)
    return (str(d.year if d.month >= 4 else d.year - 1), str((d.month - 4) % 12 + 1).zfill(3))


ORDER_NO, QUOTE_NO, RETURN_NO = Seq(10001), Seq(20000001), Seq(60000001)
DLV_NO, RDLV_NO, BILL_NO = Seq(80000001), Seq(84000001), Seq(90000001)
MATDOC_NO, ACC_NO, KNUMV_NO = Seq(4900000001), Seq(9000000001), Seq(1)
CLERKS = ["SD_CLERK01", "SD_CLERK02", "SD_CLERK03"]
PLANT_REGION = "13"  # Maharashtra

# ---------------------------------------------------------------------------
# 1. Organisation / customizing
# ---------------------------------------------------------------------------
add("T001", bukrs="IN01", butxt="Demo India Pvt Ltd", ort01="Pune", land1="IN",
    waers="INR", spras="E", ktopl="INT")
for werks, name, city, pin in [("1000", "Pune Plant - Bhosari", "Pune", "411026"),
                               ("1100", "Chakan Plant", "Chakan", "410501")]:
    add("T001W", werks=werks, name1=name, bwkey=werks, vkorg="1000", vtweg="10", spart="00",
        land1="IN", regio="13", ort01=city, pstlz=pin)
add("TVKO", vkorg="1000", waers="INR", bukrs="IN01", kunnr=None)
for v, t in [("10", "Direct sales"), ("20", "Distributors")]:
    add("TVTW", vtweg=v, vtext=t)
for s, t in [("00", "Cross-division"), ("10", "Power Distribution"), ("20", "Industrial Control")]:
    add("TSPA", spart=s, vtext=t)
for v in ("10", "20"):
    add("TVTA", vkorg="1000", vtweg=v, spart="00")
for a, vt, nk, t in [("OR", "C", "01", "Standard Order"), ("RE", "H", "02", "Returns"),
                     ("QT", "B", "03", "Quotation"), ("CR", "K", "04", "Credit Memo Request")]:
    add("TVAK", auart=a, vbtyp=vt, numki=nk, bezei=t)
for l, vt, t in [("LF", "J", "Outbound Delivery"), ("LR", "T", "Returns Delivery")]:
    add("TVLK", lfart=l, vbtyp=vt, bezei=t)
for f, vt, ft, t in [("F2", "M", "L", "Invoice"), ("F1", "M", "A", "Order-Related Inv."),
                     ("S1", "N", "L", "Invoice Cancellation"), ("G2", "O", "A", "Credit Memo"),
                     ("RE", "O", "A", "Credit for Returns")]:
    add("TVFK", fkart=f, vbtyp=vt, fktyp=ft, bezei=t)

# ---------------------------------------------------------------------------
# 2. Business partners / customers
# ---------------------------------------------------------------------------
# kunnr, name, city, street, pin, region, gst state, channel, account group, district, office
CUSTOMERS = [
    ("0001000001", "Shakti Infra Projects Pvt Ltd", "Pune", "Baner Road 14", "411045", "13", "27", "10", "0001", "IN-WST", "PUN1"),
    ("0001000002", "Narmada Power Systems Ltd", "Ahmedabad", "SG Highway 220", "380015", "06", "24", "10", "0001", "IN-WST", "PUN1"),
    ("0001000003", "Kaveri Builders & Developers", "Bengaluru", "Outer Ring Road 88", "560066", "10", "29", "10", "0001", "IN-STH", "BLR1"),
    ("0001000004", "Coromandel Electricals", "Chennai", "Anna Salai 410", "600002", "22", "33", "10", "0001", "IN-STH", "BLR1"),
    ("0001000005", "Yamuna Facility Services", "New Delhi", "Nehru Place 7", "110019", "25", "07", "10", "0001", "IN-NTH", "DEL1"),
    ("0001000006", "Vidarbha Switchgear Traders", "Nagpur", "Central Avenue 31", "440018", "13", "27", "20", "0001", "IN-WST", "PUN1"),
    ("0001000007", "Konkan Electro Distributors", "Mumbai", "Andheri MIDC 55", "400093", "13", "27", "20", "0001", "IN-WST", "PUN1"),
    ("0001000008", "Malwa Electrical Stores", "Indore", "AB Road 120", "452010", "12", "23", "20", "0001", "IN-NTH", "DEL1"),
    ("0001000009", "Shakti Infra - Hinjewadi Site", "Pune", "Hinjewadi Phase 3", "411057", "13", "27", "10", "0002", "IN-WST", "PUN1"),
    ("0001000010", "Narmada Power - Vadodara Site", "Vadodara", "GIDC Makarpura", "390010", "06", "24", "10", "0002", "IN-WST", "PUN1"),
]
CUST = {c[0]: c for c in CUSTOMERS}
ALT_SHIP_TO = {"0001000001": "0001000009", "0001000002": "0001000010"}
SOLD_TO = [c[0] for c in CUSTOMERS if c[8] == "0001"]

for i, (kunnr, name, city, street, pin, reg, gst, ch, ktokd, bzirk, vkbur) in enumerate(CUSTOMERS):
    crdat = D(2025, 4, 1) + dt.timedelta(days=17 * i)
    g = guid()
    add("BUT000", partner=kunnr, type="2", bu_group="BPCU", partner_guid=g, name_org1=name[:40],
        crusr="MDM_ADMIN", crdat=crdat, crtim=tm(), chusr=None, chdat=None, chtim=None,
        xdele=None, xblck=None)
    add("CVI_CUST_LINK", partner_guid=g, customer=kunnr)
    gstin = f"{gst}AAAC{chr(65 + i)}{1200 + i * 37:04d}{chr(70 + i % 5)}1Z{i % 10}"
    add("KNA1", kunnr=kunnr, land1="IN", name1=name[:35], name2=None, ort01=city, pstlz=pin,
        regio=reg, stras=street, telf1=f"+91 20 4{i:03d} 55{i:02d}", adrnr=str(5000 + i).zfill(10),
        ktokd=ktokd, stcd3=gstin, brsch="CONS" if ch == "10" else "TRAD", erdat=crdat,
        ernam="MDM_ADMIN", aufsd=None, lifsd=None, faksd=None, loevm=None)
    add("KNB1", kunnr=kunnr, bukrs="IN01", akont="0000121000",
        zterm="NT30" if ch == "10" else "NT45", zwels="T", erdat=crdat, ernam="MDM_ADMIN", loevm=None)
    add("KNVV", kunnr=kunnr, vkorg="1000", vtweg=ch, spart="00", kdgrp="01" if ch == "10" else "02",
        bzirk=bzirk, vkbur=vkbur, vkgrp="101" if ch == "10" else "201", waers="INR", kalks="1",
        konda="01" if ch == "10" else "02", pltyp="01", vsbed="01", vwerk="1000", inco1="DAP",
        inco2=city, zterm="NT30" if ch == "10" else "NT45", ktgrd="01", aufsd=None, lifsd=None,
        faksd=None, erdat=crdat, ernam="MDM_ADMIN", loevm=None)
    funcs = ["AG", "WE", "RE", "RG"] if ktokd == "0001" else ["WE"]
    for parvw in funcs:
        add("KNVP", kunnr=kunnr, vkorg="1000", vtweg=ch, spart="00", parvw=parvw, parza="000",
            kunn2=kunnr, lifnr=None, pernr=None, defpa="X")
    if kunnr in ALT_SHIP_TO:
        add("KNVP", kunnr=kunnr, vkorg="1000", vtweg=ch, spart="00", parvw="WE", parza="001",
            kunn2=ALT_SHIP_TO[kunnr], lifnr=None, pernr=None, defpa=None)

# ---------------------------------------------------------------------------
# 3. Materials
# ---------------------------------------------------------------------------
# matnr, description, type, group, unit, list price INR, division, net kg, prod hierarchy, item cat group
MATERIALS = [
    ("MCB-C16-1P", "Miniature Circuit Breaker C16 1P", "HAWA", "ELE-MCB", "EA", 240.00, "10", 0.12, "001001001", "NORM"),
    ("MCB-C32-3P", "Miniature Circuit Breaker C32 3P", "HAWA", "ELE-MCB", "EA", 980.00, "10", 0.36, "001001002", "NORM"),
    ("RCCB-40A-4P", "RCCB 40A 4P 30mA", "HAWA", "ELE-MCB", "EA", 3450.00, "10", 0.45, "001001003", "NORM"),
    ("MCCB-250A-3P", "MCCB 250A 3P 36kA", "FERT", "ELE-MCCB", "EA", 21500.00, "10", 3.20, "001002001", "NORM"),
    ("ACB-1600A-4P", "Air Circuit Breaker 1600A 4P", "FERT", "ELE-ACB", "EA", 285000.00, "10", 68.0, "001003001", "NORM"),
    ("CONT-25A-AC3", "Contactor 25A AC3 230V Coil", "HAWA", "CTL-CONT", "EA", 1850.00, "20", 0.38, "002001001", "NORM"),
    ("OLR-9-13A", "Thermal Overload Relay 9-13A", "HAWA", "CTL-CONT", "EA", 1450.00, "20", 0.15, "002001002", "NORM"),
    ("VFD-7.5KW", "Variable Frequency Drive 7.5kW", "FERT", "CTL-DRV", "EA", 48500.00, "20", 4.80, "002002001", "NORM"),
    ("UPS-10KVA-ONL", "Online UPS 10kVA", "FERT", "PWR-UPS", "EA", 162000.00, "10", 72.0, "001004001", "NORM"),
    ("PNL-LT-800A", "LT Distribution Panel 800A", "FERT", "PWR-PNL", "EA", 645000.00, "10", 410.0, "001005001", "NORM"),
    ("CBL-4C-16SQ", "Armoured Cable 4C x 16 sq mm", "HAWA", "CBL-LT", "M", 420.00, "10", 0.95, "001006001", "NORM"),
    ("SRV-AMC-STD", "Annual Maintenance Contract - Standard", "DIEN", "SRV-AMC", "EA", 25000.00, "00", 0.0, "009001001", "LEIS"),
]
MAT = {m[0]: m for m in MATERIALS}
GOODS = [m[0] for m in MATERIALS if m[2] != "DIEN"]

for i, (matnr, txt, mtart, matkl, meins, price, spart, kg, prdha, mtpos) in enumerate(MATERIALS):
    ersda = D(2025, 1, 6) + dt.timedelta(days=11 * i)
    add("MARA", matnr=matnr, ersda=ersda, ernam="MDM_ADMIN", laeda=ersda + dt.timedelta(days=200),
        aenam="MDM_ADMIN", lvorm=None, mtart=mtart, mbrsh="M", matkl=matkl, meins=meins,
        brgew=round(kg * 1.1, 3) if kg else None, ntgew=kg or None, gewei="KG" if kg else None,
        volum=None, voleh=None, spart=spart, prdha=prdha, ean11=None if mtart == "DIEN" else f"890{1000000000 + i * 7919}")
    add("MAKT", matnr=matnr, spras="E", maktx=txt, maktg=txt.upper())
    plants = ["1000"] if mtart == "DIEN" or i % 3 else ["1000", "1100"]
    for w in plants:
        add("MARC", matnr=matnr, werks=w, mmsta=None, ladgr=None if mtart == "DIEN" else "0001",
            mtvfp="02", prctr="PC" + w, dispo="001", lvorm=None)
    for ch in ("10", "20"):
        add("MVKE", matnr=matnr, vkorg="1000", vtweg=ch, vmsta=None, dwerk="1000", mtpos=mtpos,
            kondm="01", ktgrm="01" if mtart != "DIEN" else "02", prodh=prdha, vrkme=meins,
            aumng=None, lvorm=None)


# ---------------------------------------------------------------------------
# Helpers for transactional data
# ---------------------------------------------------------------------------
def price_items(items, channel, intra, kdatu):
    """items: list of (kposn, matnr, qty). Writes PRCD_ELEMENTS, returns knumv and {kposn: (net, tax)}."""
    knumv = KNUMV_NO.next()
    out = {}
    for kposn, matnr, qty in items:
        unit, list_price = MAT[matnr][4], MAT[matnr][5]
        gross = round(list_price * qty, 2)
        conds = [("010", "PR00", "C", list_price, gross, "B", gross)]
        net = gross
        if channel == "20":
            disc = round(-gross * 0.05, 2)
            conds.append(("100", "K004", "A", -5.0, disc, "A", gross))
            net = round(gross + disc, 2)
        if intra:
            cg = round(net * 0.09, 2)
            conds += [("800", "JOCG", "A", 9.0, cg, "D", net), ("810", "JOSG", "A", 9.0, cg, "D", net)]
            tax = round(cg * 2, 2)
        else:
            tax = round(net * 0.18, 2)
            conds.append(("820", "JOIG", "A", 18.0, tax, "D", net))
        for stunr, kschl, krech, kbetr, kwert, koaid, kawrt in conds:
            add("PRCD_ELEMENTS", knumv=knumv, kposn=kposn, stunr=stunr, zaehk="001", kschl=kschl,
                kdatu=kdatu, krech=krech, kbetr=kbetr, waers="INR", kpein=1 if krech == "C" else None,
                kmein=unit if krech == "C" else None, kawrt=kawrt if krech == "A" else qty,
                kwert=kwert, koaid=koaid, kstat=None, kinak=None, kherk="A")
        out[kposn] = (net, tax)
    return knumv, out


def flow(vbelv, posnv, vtyp_v, vbeln, posnn, vtyp_n, qty, unit, value, matnr, d, plmin="+"):
    add("VBFA", ruuid=guid(), vbelv=vbelv, posnv=posnv, vbtyp_v=vtyp_v, vbeln=vbeln, posnn=posnn,
        vbtyp_n=vtyp_n, rfmng=qty, meins=unit, rfwrt=value, waers="INR", matnr=matnr,
        plmin=plmin, erdat=d, erzet=tm())


def partners(vbeln, ag, we, with_bill=True):
    for parvw, kunnr in [("AG", ag), ("WE", we)] + ([("RE", ag), ("RG", ag)] if with_bill else []):
        add("VBPA", vbeln=vbeln, posnr="000000", parvw=parvw, kunnr=kunnr, lifnr=None, pernr=None,
            parnr=None, adrnr=str(5000 + int(kunnr[-2:]) - 1).zfill(10), land1="IN")


def status(values):
    vals = [v for v in values if v]
    if not vals:
        return None
    if all(v == "C" for v in vals):
        return "C"
    if all(v == "A" for v in vals):
        return "A"
    return "B"


ORDERS = {}  # vbeln -> dict with header info and items


def create_sales_doc(auart, vbtyp, number, d, ag, we, plant, lines, ref=None, augru=None,
                     valid=None, credit_block=False, sched_split=None):
    """lines: list of (matnr, qty, rejected). Creates VBAK/VBAP/VBEP/VBKD/VBPA/PRCD rows."""
    ch, intra = CUST[ag][7], CUST[ag][5] == PLANT_REGION
    items = [(posnr(i + 1), m, q) for i, (m, q, _) in enumerate(lines)]
    knumv, priced = price_items(items, ch, intra, d)
    clerk, erzet, vdatu = random.choice(CLERKS), tm(), d + dt.timedelta(days=random.randint(4, 7))
    doc = dict(vbeln=number, auart=auart, vbtyp=vbtyp, date=d, ag=ag, we=we, ch=ch, plant=plant,
               intra=intra, knumv=knumv, items={}, header={}, vdatu=vdatu)
    for (p, m, q), (_, _, rej) in zip(items, lines):
        unit, service = MAT[m][4], MAT[m][2] == "DIEN"
        net, tax = priced[p]
        doc["items"][p] = dict(matnr=m, qty=q, unit=unit, net=net, tax=tax, rejected=rej,
                               service=service, delivered=0, billed=0)
        add("VBAP", vbeln=number, posnr=p, matnr=m, arktx=MAT[m][1], pstyv=(
            "AGN" if vbtyp == "B" else "REN" if vbtyp == "H" else "TAD" if service else "TAN"),
            uepos=None, abgru="01" if rej else None, matkl=MAT[m][3], prodh=MAT[m][8], kwmeng=q,
            vrkme=unit, meins=unit, umvkz=1, umvkn=1, netpr=round(net / q, 2), kpein=1, kmein=unit,
            netwr=net, mwsbp=tax, waerk="INR", werks=plant, lgort=None if service else "0001",
            vstel=None if service else plant, route=None if service else ("R00001" if intra else "R00002"),
            prctr="PC" + plant, vgbel=ref[0] if ref else None, vgpos=(ref[1].get(p) if ref else None),
            erdat=d, erzet=erzet, ernam=clerk, aedat=None,
            gbsta=None, absta=None, lfsta=None, fksta=None)  # statuses filled in finalize()
        if sched_split and p in sched_split:
            first, later = sched_split[p]
            for etenr, (q_conf, dd) in enumerate([(first, vdatu), (later, vdatu + dt.timedelta(days=21))], 1):
                add("VBEP", vbeln=number, posnr=p, etenr=str(etenr).zfill(4), ettyp="CP", edatu=dd,
                    wmeng=q if etenr == 1 else 0, bmeng=q_conf, vrkme=unit, lmeng=q_conf, meins=unit,
                    mbdat=dd - dt.timedelta(days=2), lddat=dd - dt.timedelta(days=2),
                    wadat=dd - dt.timedelta(days=1), tddat=dd - dt.timedelta(days=2), lifsp=None)
        elif not service and vbtyp != "B":
            add("VBEP", vbeln=number, posnr=p, etenr="0001", ettyp="CP" if vbtyp == "C" else "DN",
                edatu=vdatu, wmeng=q, bmeng=0 if rej else q, vrkme=unit, lmeng=q, meins=unit,
                mbdat=vdatu - dt.timedelta(days=2), lddat=vdatu - dt.timedelta(days=2),
                wadat=vdatu - dt.timedelta(days=1), tddat=vdatu - dt.timedelta(days=2), lifsp=None)
    doc["header"] = dict(
        vbeln=number, erdat=d, erzet=erzet, ernam=clerk, aedat=None, audat=d, vbtyp=vbtyp,
        trvog="2" if vbtyp == "B" else "0", auart=auart, augru=augru, lifsk=None, faksk=None,
        netwr=round(sum(i["net"] for i in doc["items"].values() if not i["rejected"]), 2),
        waerk="INR", vkorg="1000", vtweg=ch, spart="00", vkgrp=CUST[ag][10] and ("101" if ch == "10" else "201"),
        vkbur=CUST[ag][10], guebg=valid[0] if valid else None, gueen=valid[1] if valid else None,
        knumv=knumv, vdatu=vdatu, bstnk=f"PO/{CUST[ag][1].split()[0].upper()}/{random.randint(1000, 9999)}",
        bstdk=d - dt.timedelta(days=1), kunnr=ag, kkber="1000", bukrs_vf="IN01",
        vgbel=ref[0] if ref else None,
        gbstk=None, abstk=None, lfstk=None, fkstk=None, cmgst="B" if credit_block else "A",
        spstg="C" if credit_block else "A")
    add("VBKD", vbeln=number, posnr="000000", zterm="NT30" if ch == "10" else "NT45", inco1="DAP",
        inco2=CUST[we][2], bstkd=doc["header"]["bstnk"], prsdt=d, fkdat=None, kursk=1.0,
        kdgrp="01" if ch == "10" else "02", bzirk=CUST[ag][9], konda="01" if ch == "10" else "02",
        pltyp="01", ktgrd="01")
    partners(number, ag, we)
    ORDERS[number] = doc
    return doc


DELIVERIES = {}


def create_delivery(order, qtys, d, picked=True, gi=True, returns=False):
    vbeln = (RDLV_NO if returns else DLV_NO).next()
    clerk, erzet = "WH_USER01", tm(7, 20)
    dl = dict(vbeln=vbeln, order=order["vbeln"], date=d, gi=gi, picked=picked, billed=False,
              items={}, ag=order["ag"], we=order["we"], returns=returns, gi_date=d if gi else None)
    tot_n = tot_b = 0.0
    for i, (op, q) in enumerate(qtys.items(), 1):
        oi = order["items"][op]
        m, unit = oi["matnr"], oi["unit"]
        p = posnr(i)
        n_kg = round(MAT[m][7] * q, 3)
        tot_n += n_kg
        tot_b += round(n_kg * 1.1, 3)
        dl["items"][p] = dict(matnr=m, qty=q, unit=unit, order_pos=op)
        add("LIPS", vbeln=vbeln, posnr=p, pstyv="REN" if returns else "TAN", matnr=m, arktx=MAT[m][1],
            matkl=MAT[m][3], werks=order["plant"], lgort="0001", charg=None, lfimg=q, vrkme=unit,
            lgmng=q, meins=unit, ntgew=n_kg, brgew=round(n_kg * 1.1, 3), gewei="KG",
            vgbel=order["vbeln"], vgpos=op, prctr="PC" + order["plant"], erdat=d, erzet=erzet,
            ernam=clerk, aedat=None, gbsta=None, kosta=None, wbsta=None, fksta=None)
        value = round(oi["net"] * q / oi["qty"], 2)
        flow(order["vbeln"], op, order["vbtyp"], vbeln, p, "T" if returns else "J", q, unit, value, m, d)
        if gi:
            flow(vbeln, p, "T" if returns else "J", str(MATDOC_NO.n).zfill(10), "0001",
                 "h" if returns else "R", q, unit, value, m, d)
        oi["delivered"] += q
    if gi:
        MATDOC_NO.next()
    dl["header"] = dict(vbeln=vbeln, ernam=clerk, erzet=erzet, erdat=d, aedat=None, vstel=order["plant"],
                        vkorg="1000", lfart="LR" if returns else "LF", vbtyp="T" if returns else "J",
                        route=None if returns else ("R00001" if order["intra"] else "R00002"),
                        lfdat=d + dt.timedelta(days=0 if returns else 2), kodat=d, lddat=d,
                        wadat=d, wadat_ist=d if gi else None, kunnr=order["we"], kunag=order["ag"],
                        btgew=round(tot_b, 3), ntgew=round(tot_n, 3), gewei="KG",
                        anzpk=random.randint(1, 6), inco1="DAP", inco2=CUST[order["we"]][2], lifsk=None,
                        gbstk=None, kostk=None, wbstk=None, fkstk=None)
    partners(vbeln, order["ag"], order["we"], with_bill=False)
    DELIVERIES[vbeln] = dl
    return dl


BILLS = {}


def create_bill(fkart, vbtyp, d, ag, we, lines, src_type, cancels=None):
    """lines: list of (matnr, qty, ref_doc, ref_pos, order_vbeln, order_pos)."""
    vbeln = BILL_NO.next()
    ch, intra = CUST[ag][7], CUST[ag][5] == PLANT_REGION
    items = [(posnr(i + 1), l[0], l[1]) for i, l in enumerate(lines)]
    knumv, priced = price_items(items, ch, intra, d)
    gjahr, poper = fiscal(d)
    erzet = tm(20, 23)
    net_total = tax_total = 0.0
    for (p, m, q), (_, _, rdoc, rpos, ov, op) in zip(items, lines):
        net, tax = priced[p]
        net_total += net
        tax_total += tax
        o = ORDERS[ov]
        add("VBRP", vbeln=vbeln, posnr=p, fkimg=q, vrkme=MAT[m][4], fklmg=q, meins=MAT[m][4], netwr=net,
            mwsbp=tax, wavwr=round(net * 0.68, 2), matnr=m, arktx=MAT[m][1], matkl=MAT[m][3],
            prodh=MAT[m][8], pstyv=o["items"][op] and ("TAD" if MAT[m][2] == "DIEN" else "REN" if o["vbtyp"] == "H" else "TAN"),
            werks=o["plant"], prctr="PC" + o["plant"], vgbel=rdoc, vgpos=rpos, vgtyp=src_type,
            aubel=ov, aupos=op, erdat=d, erzet=erzet, ernam="BATCH_BILL")
        if cancels:
            flow(cancels, p, "M", vbeln, p, "N", q, MAT[m][4], net, m, d, plmin="-")
        else:
            flow(rdoc, rpos, src_type, vbeln, p, vbtyp, q, MAT[m][4], net, m, d,
                 plmin="-" if vbtyp == "O" else "+")
    add("VBRK", vbeln=vbeln, fkart=fkart, fktyp="A" if fkart in ("F1", "RE", "G2") else "L", vbtyp=vbtyp,
        waerk="INR", vkorg="1000", vtweg=ch, spart="00", knumv=knumv, fkdat=d, gjahr=gjahr, poper=poper,
        bukrs="IN01", netwr=round(net_total, 2), mwsbk=round(tax_total, 2), kurrf=1.0, kunrg=ag, kunag=ag,
        zterm="NT30" if ch == "10" else "NT45", xblnr=f"IN01/2627/{int(vbeln) - 90000000:05d}",
        belnr=ACC_NO.next(), rfbsk="C", fksto=None, sfakn=cancels, ernam="BATCH_BILL", erzet=erzet,
        erdat=d, aedat=None, gbstk="C", buchk="C")
    add("VBPA", vbeln=vbeln, posnr="000000", parvw="AG", kunnr=ag, lifnr=None, pernr=None, parnr=None,
        adrnr=str(5000 + int(ag[-2:]) - 1).zfill(10), land1="IN")
    for parvw in ("RE", "RG"):
        add("VBPA", vbeln=vbeln, posnr="000000", parvw=parvw, kunnr=ag, lifnr=None, pernr=None,
            parnr=None, adrnr=str(5000 + int(ag[-2:]) - 1).zfill(10), land1="IN")
    add("VBPA", vbeln=vbeln, posnr="000000", parvw="WE", kunnr=we, lifnr=None, pernr=None, parnr=None,
        adrnr=str(5000 + int(we[-2:]) - 1).zfill(10), land1="IN")
    BILLS[vbeln] = dict(lines=lines, items=items, ag=ag, we=we, date=d)
    return vbeln


def bill_delivery(dl, d):
    o = ORDERS[dl["order"]]
    lines = [(it["matnr"], it["qty"], dl["vbeln"], p, o["vbeln"], it["order_pos"]) for p, it in dl["items"].items()]
    inv = create_bill("F2", "M", d, o["ag"], o["we"], lines, "J")
    dl["billed"] = True
    for it in dl["items"].values():
        o["items"][it["order_pos"]]["billed"] += it["qty"]
    return inv


def cancel_bill(inv, d):
    b = BILLS[inv]
    canc = create_bill("S1", "N", d, b["ag"], b["we"], b["lines"], "M", cancels=inv)
    for r in rows["VBRK"]:
        if r["VBELN"] == inv:
            r["FKSTO"] = "X"
            r["AEDAT"] = d
    return canc


def pick_lines(n_items):
    mats = random.sample(GOODS, n_items)
    out = []
    for m in mats:
        price = MAT[m][5]
        if MAT[m][4] == "M":
            q = random.choice([50, 100, 150, 250, 500])
        elif price < 2000:
            q = random.choice([10, 20, 25, 50, 100, 150])
        elif price < 50000:
            q = random.randint(2, 20)
        else:
            q = random.randint(1, 3)
        out.append((m, q, False))
    return out


# ---------------------------------------------------------------------------
# 4. Transactions
# ---------------------------------------------------------------------------
TODAY = D(2026, 10, 18)
scenario = {2: "rejected", 5: "cancel_rebill", 8: "from_quote", 10: "service",
            18: "partial", 19: "gi_not_billed", 20: "picked", 21: "credit_block", 22: "open", 23: "open"}
returned_invoice = None
RETURN_SOURCE_IDX = 3

for idx in range(N_ORDERS):
    d = D(2026, 9, 1) + dt.timedelta(days=round(idx * 46 / (N_ORDERS - 1)))
    kind = scenario.get(idx, "full")
    ag = SOLD_TO[idx % len(SOLD_TO)]
    we = ALT_SHIP_TO[ag] if ag in ALT_SHIP_TO and idx % 2 else ag
    plant = "1100" if idx % 4 == 3 else "1000"

    if kind == "service":
        doc = create_sales_doc("OR", "C", ORDER_NO.next(), d, ag, we, plant, [("SRV-AMC-STD", 1, False)])
        bill_d = d + dt.timedelta(days=1)
        create_bill("F1", "M", bill_d, ag, we, [("SRV-AMC-STD", 1, doc["vbeln"], "000010", doc["vbeln"], "000010")], "C")
        doc["items"]["000010"]["billed"] = 1
        continue

    lines = pick_lines(random.randint(1, 4))
    ref = None
    if kind == "rejected" and len(lines) < 2:
        lines += pick_lines(1)
    if kind == "rejected":
        lines[-1] = (lines[-1][0], lines[-1][1], True)
    if kind == "from_quote":
        qd = d - dt.timedelta(days=6)
        q = create_sales_doc("QT", "B", QUOTE_NO.next(), qd, ag, we, plant, lines,
                             valid=(qd, qd + dt.timedelta(days=30)))
        ref = (q["vbeln"], {p: p for p in q["items"]})
        for p, it in q["items"].items():
            flow(q["vbeln"], p, "B", str(ORDER_NO.n).zfill(10), p, "C", it["qty"], it["unit"],
                 it["net"], it["matnr"], d)
    split = None
    if kind == "partial":
        lines = [(m, max(q, 4), r) for m, q, r in lines]
        first_pos, (m0, q0, _) = posnr(1), lines[0]
        split = {first_pos: (q0 - q0 // 2, q0 // 2)}
    doc = create_sales_doc("OR", "C", ORDER_NO.next(), d, ag, we, plant, lines, ref=ref,
                           credit_block=(kind == "credit_block"), sched_split=split)
    if kind in ("credit_block", "open"):
        continue

    to_ship = {p: it["qty"] for p, it in doc["items"].items() if not it["rejected"]}
    if kind == "partial":
        to_ship[posnr(1)] = split[posnr(1)][0]
    dlv_d = min(d + dt.timedelta(days=random.randint(2, 4)), TODAY - dt.timedelta(days=1))
    dl = create_delivery(doc, to_ship, dlv_d, picked=True, gi=(kind != "picked"))
    if kind in ("picked", "gi_not_billed"):
        continue
    inv = bill_delivery(dl, dlv_d)
    if kind == "cancel_rebill":
        cancel_bill(inv, dlv_d + dt.timedelta(days=1))
        for it in dl["items"].values():
            doc["items"][it["order_pos"]]["billed"] -= it["qty"]
        bill_delivery(dl, dlv_d + dt.timedelta(days=1))
    if idx == RETURN_SOURCE_IDX:
        returned_invoice = (inv, dl, doc)

# Open quotation
qd = D(2026, 10, 12)
create_sales_doc("QT", "B", QUOTE_NO.next(), qd, SOLD_TO[4], SOLD_TO[4], "1000",
                 [("UPS-10KVA-ONL", 2, False), ("SRV-AMC-STD", 1, False)],
                 valid=(qd, qd + dt.timedelta(days=30)))

# Customer return against one invoice: return part of the first line
inv, src_dl, src_order = returned_invoice
src_pos, src_item = next(iter(src_dl["items"].items()))
ret_qty = max(1, src_item["qty"] // 4)
rd = D(2026, 10, 1)
ret = create_sales_doc("RE", "H", RETURN_NO.next(), rd, src_order["ag"], src_order["we"], src_order["plant"],
                       [(src_item["matnr"], ret_qty, False)], ref=(inv, {"000010": src_pos}), augru="101")
flow(inv, src_pos, "M", ret["vbeln"], "000010", "H", ret_qty, src_item["unit"], ret["items"]["000010"]["net"],
     src_item["matnr"], rd, plmin="-")
rdl = create_delivery(ret, {"000010": ret_qty}, rd + dt.timedelta(days=2), gi=True, returns=True)
create_bill("RE", "O", rd + dt.timedelta(days=3), ret["ag"], ret["we"],
            [(src_item["matnr"], ret_qty, ret["vbeln"], "000010", ret["vbeln"], "000010")], "H")
ret["items"]["000010"]["billed"] = ret_qty
rdl["billed"] = True


# ---------------------------------------------------------------------------
# 5. Statuses
# ---------------------------------------------------------------------------
def finalize():
    for doc in ORDERS.values():
        item_stats = []
        for p, it in doc["items"].items():
            r = next(r for r in rows["VBAP"] if r["VBELN"] == doc["vbeln"] and r["POSNR"] == p)
            if doc["vbtyp"] == "B":  # quotation: complete once referenced
                referenced = any(v["VBELV"] == doc["vbeln"] and v["VBTYP_N"] == "C" for v in rows["VBFA"])
                r["GBSTA"] = "C" if referenced else "A"
            elif it["rejected"]:
                r.update(ABSTA="C", GBSTA="C")
            else:
                r["ABSTA"] = "A"
                if it["service"]:
                    r["FKSTA"] = "C" if it["billed"] >= it["qty"] else "A"
                    r["GBSTA"] = r["FKSTA"]
                else:
                    r["LFSTA"] = "C" if it["delivered"] >= it["qty"] else ("B" if it["delivered"] else "A")
                    if doc["vbtyp"] == "H":  # returns: order-related credit memo
                        r["FKSTA"] = "C" if it["billed"] >= it["qty"] else "A"
                        r["GBSTA"] = "C" if r["LFSTA"] == "C" and r["FKSTA"] == "C" else ("A" if r["LFSTA"] == "A" else "B")
                    else:
                        r["GBSTA"] = r["LFSTA"]
            item_stats.append(r)
        h = doc["header"]
        h["gbstk"] = status([r["GBSTA"] for r in item_stats])
        h["abstk"] = status([r["ABSTA"] for r in item_stats])
        h["lfstk"] = status([r["LFSTA"] for r in item_stats])
        h["fkstk"] = status([r["FKSTA"] for r in item_stats])
        add("VBAK", **h)
    for dl in DELIVERIES.values():
        lips = [r for r in rows["LIPS"] if r["VBELN"] == dl["vbeln"]]
        for r in lips:
            r["KOSTA"] = "C" if dl["picked"] else "A"
            r["WBSTA"] = "C" if dl["gi"] else "A"
            r["FKSTA"] = None if dl["returns"] else ("C" if dl["billed"] else "A")
            r["GBSTA"] = "C" if (dl["billed"] or dl["returns"]) and dl["gi"] else ("B" if dl["gi"] or dl["picked"] else "A")
        h = dl["header"]
        h["kostk"] = status([r["KOSTA"] for r in lips])
        h["wbstk"] = status([r["WBSTA"] for r in lips])
        h["fkstk"] = status([r["FKSTA"] for r in lips])
        h["gbstk"] = status([r["GBSTA"] for r in lips])
        add("LIKP", **h)


finalize()


# ---------------------------------------------------------------------------
# 6. Validation
# ---------------------------------------------------------------------------
def validate():
    errors = []
    for t in TABLES:
        if not rows[t]:
            errors.append(f"{t} has no rows")
        seen = set()
        for r in rows[t]:
            k = tuple(r[c] for c in PKS[t])
            if k in seen:
                errors.append(f"duplicate PK in {t}: {k}")
            seen.add(k)
    vbap = defaultdict(float)
    for r in rows["VBAP"]:
        if not r["ABGRU"]:
            vbap[r["VBELN"]] += r["NETWR"]
    for r in rows["VBAK"]:
        if abs(vbap[r["VBELN"]] - r["NETWR"]) > 0.01:
            errors.append(f"VBAK {r['VBELN']} net {r['NETWR']} != items {vbap[r['VBELN']]}")
    vbrp = defaultdict(float)
    for r in rows["VBRP"]:
        vbrp[r["VBELN"]] += r["NETWR"]
    for r in rows["VBRK"]:
        if abs(vbrp[r["VBELN"]] - r["NETWR"]) > 0.01:
            errors.append(f"VBRK {r['VBELN']} net mismatch")
    vbap_keys = {(r["VBELN"], r["POSNR"]) for r in rows["VBAP"]}
    for r in rows["LIPS"]:
        if (r["VGBEL"], r["VGPOS"]) not in vbap_keys:
            errors.append(f"LIPS {r['VBELN']}/{r['POSNR']} references missing order item")
    for r in rows["VBRP"]:
        if (r["AUBEL"], r["AUPOS"]) not in vbap_keys:
            errors.append(f"VBRP {r['VBELN']}/{r['POSNR']} references missing order item")
    knumvs = {r["KNUMV"] for r in rows["PRCD_ELEMENTS"]}
    for t in ("VBAK", "VBRK"):
        for r in rows[t]:
            if r["KNUMV"] not in knumvs:
                errors.append(f"{t} {r['VBELN']} has no conditions")
    kunnrs = {r["KUNNR"] for r in rows["KNA1"]}
    for r in rows["VBPA"]:
        if r["KUNNR"] not in kunnrs:
            errors.append(f"VBPA unknown customer {r['KUNNR']}")
    if errors:
        raise SystemExit("Validation failed:\n" + "\n".join(errors))


validate()


# ---------------------------------------------------------------------------
# 7. Write SQL
# ---------------------------------------------------------------------------
def lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, Raw):
        return f"HEXTORAW('{v}')"
    if isinstance(v, dt.date):
        return f"DATE '{v.isoformat()}'"
    if isinstance(v, bool):
        return "'X'" if v else "NULL"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        s = f"{v:.9f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return "'" + str(v).replace("'", "''") + "'"


with open(OUT, "w", encoding="utf-8") as f:
    f.write("/* =====================================================================\n"
            "   Sample data for SAP S/4HANA SD tables (s4_sd_oracle_ddl.sql)\n"
            f"   Generated by gen_s4_sd_sample.py (seed {SEED}). Client 100, company code IN01.\n"
            "   Re-runnable: clears all 30 tables first (this replaces the seed rows\n"
            "   inserted by the DDL script).\n"
            "   ===================================================================== */\n\n"
            "SET DEFINE OFF\n-- ALTER SESSION SET CURRENT_SCHEMA = SAPSD;\n\n")
    f.write("-- Clear existing data\n")
    for t in reversed(TABLES):
        f.write(f"DELETE FROM {t};\n")
    f.write("\n")
    for t in TABLES:
        f.write(f"-- {t} ({len(rows[t])} rows)\n")
        for r in rows[t]:
            cols = ", ".join(r.keys())
            vals = ", ".join(lit(v) for v in r.values())
            f.write(f"INSERT INTO {t} ({cols}) VALUES ({vals});\n")
        f.write("\n")
    f.write("COMMIT;\n\n")
    f.write("""/* ---------------------------------------------------------------------
   Sanity checks
   ---------------------------------------------------------------------
-- Row counts
SELECT 'VBAK' t, COUNT(*) FROM vbak UNION ALL SELECT 'VBAP', COUNT(*) FROM vbap
UNION ALL SELECT 'LIKP', COUNT(*) FROM likp UNION ALL SELECT 'VBRK', COUNT(*) FROM vbrk;

-- Net revenue: invoices minus cancellations and credit memos.
-- Summing VBRK.NETWR blindly double-counts the cancelled-and-rebilled invoice.
SELECT SUM(CASE WHEN vbtyp = 'M' THEN netwr
                WHEN vbtyp IN ('N', 'O') THEN -netwr END) AS net_revenue_inr
FROM vbrk;

-- Full document flow for one order
SELECT vbelv, posnv, vbtyp_v, vbeln, posnn, vbtyp_n, rfmng, rfwrt
FROM vbfa START WITH vbelv = '0000010006'
CONNECT BY NOCYCLE PRIOR vbeln = vbelv AND PRIOR posnn = posnv;
   --------------------------------------------------------------------- */
""")

print("Wrote", OUT)
for t in TABLES:
    print(f"  {t:15s} {len(rows[t]):4d}")
