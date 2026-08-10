import json
import re
from collections import Counter, defaultdict
from time import time

from app.database.connection_manager import get_master_connection


HEATMAP_CACHE_TTL_SECONDS = 90
_heatmap_cache = {}


ZIP_KEYS = {
    "zip",
    "zipcode",
    "zip_code",
    "postal",
    "postalcode",
    "postal_code",
    "destinationzip",
    "destination_zip",
    "destzip",
    "dest_zip",
    "shiptozip",
    "ship_to_zip",
    "recipientzip",
    "recipient_zip",
    "receiverzip",
    "receiver_zip",
}

WEIGHT_KEYS = {
    "weight",
    "packageweight",
    "package_weight",
    "actualweight",
    "actual_weight",
    "billableweight",
    "billable_weight",
    "billedweight",
    "billed_weight",
    "shipmentweight",
    "shipment_weight",
    "chargeableweight",
    "chargeable_weight",
    "ratedweight",
    "rated_weight",
    "lbs",
    "lb",
}

CHARGE_KEYS = {
    "charge",
    "charges",
    "amount",
    "cost",
    "totalcharge",
    "total_charge",
    "netcharge",
    "net_charge",
    "transportationcharge",
    "transportation_charge",
    "shippingcharge",
    "shipping_charge",
    "freightcharge",
    "freight_charge",
    "invoiceamount",
    "invoice_amount",
    "billedamount",
    "billed_amount",
}

SERVICE_KEYS = {
    "service",
    "servicelevel",
    "service_level",
    "servicetype",
    "service_type",
    "upsservice",
    "product",
    "shipmentservice",
}

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

US_TILE_POSITIONS = {
    "AK": (1, 1), "ME": (1, 12),
    "VT": (2, 11), "NH": (2, 12),
    "WA": (3, 2), "MT": (3, 3), "ND": (3, 4), "MN": (3, 5), "WI": (3, 6), "MI": (3, 8), "NY": (3, 10), "MA": (3, 12),
    "OR": (4, 2), "ID": (4, 3), "SD": (4, 4), "IA": (4, 5), "IL": (4, 6), "IN": (4, 7), "OH": (4, 8), "PA": (4, 9), "NJ": (4, 10), "CT": (4, 11), "RI": (4, 12),
    "CA": (5, 2), "NV": (5, 3), "WY": (5, 4), "NE": (5, 5), "MO": (5, 6), "KY": (5, 7), "WV": (5, 8), "VA": (5, 9), "MD": (5, 10), "DE": (5, 11),
    "AZ": (6, 3), "UT": (6, 4), "CO": (6, 5), "KS": (6, 6), "AR": (6, 7), "TN": (6, 8), "NC": (6, 9), "SC": (6, 10), "DC": (6, 11),
    "NM": (7, 4), "OK": (7, 6), "LA": (7, 7), "MS": (7, 8), "AL": (7, 9), "GA": (7, 10),
    "HI": (8, 1), "TX": (8, 6), "FL": (8, 11),
}

ZIP_RANGES = [
    (350, 369, "AL"), (995, 999, "AK"), (850, 865, "AZ"), (716, 729, "AR"),
    (900, 961, "CA"), (800, 816, "CO"), (60, 69, "CT"), (197, 199, "DE"),
    (320, 349, "FL"), (300, 319, "GA"), (967, 968, "HI"), (832, 838, "ID"),
    (600, 629, "IL"), (460, 479, "IN"), (500, 528, "IA"), (660, 679, "KS"),
    (400, 427, "KY"), (700, 714, "LA"), (39, 49, "ME"), (206, 219, "MD"),
    (10, 27, "MA"), (480, 499, "MI"), (550, 567, "MN"), (386, 397, "MS"),
    (630, 658, "MO"), (590, 599, "MT"), (680, 693, "NE"), (889, 898, "NV"),
    (30, 38, "NH"), (70, 89, "NJ"), (870, 884, "NM"), (100, 149, "NY"),
    (270, 289, "NC"), (580, 588, "ND"), (430, 459, "OH"), (730, 749, "OK"),
    (970, 979, "OR"), (150, 196, "PA"), (28, 29, "RI"), (290, 299, "SC"),
    (570, 577, "SD"), (370, 385, "TN"), (750, 799, "TX"), (840, 847, "UT"),
    (50, 59, "VT"), (201, 205, "VA"), (220, 246, "VA"), (980, 994, "WA"),
    (247, 268, "WV"), (530, 549, "WI"), (820, 831, "WY"), (200, 200, "DC"),
]


def normalize_key(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def normalize_zip(value):
    match = re.search(r"\d{5}", str(value or ""))
    return match.group(0) if match else None


def parse_number(value):
    if value in (None, ""):
        return None
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except Exception:
        return None


def zip_to_state(zip_code):
    if not zip_code:
        return None
    prefix = int(zip_code[:3])
    for start, end, state in ZIP_RANGES:
        if start <= prefix <= end:
            return state
    return None


def extract_zip(payload):
    for key, value in payload.items():
        if normalize_key(key) in ZIP_KEYS:
            zip_code = normalize_zip(value)
            if zip_code:
                return zip_code

    for key, value in payload.items():
        normalized = normalize_key(key)
        if "zip" in normalized or "postal" in normalized:
            zip_code = normalize_zip(value)
            if zip_code:
                return zip_code

    return None


def extract_number(payload, exact_keys, contains_terms):
    for key, value in payload.items():
        if normalize_key(key) in exact_keys:
            number = parse_number(value)
            if number is not None:
                return number

    for key, value in payload.items():
        normalized = normalize_key(key)
        if any(term in normalized for term in contains_terms):
            number = parse_number(value)
            if number is not None:
                return number

    return None


def extract_text(payload, exact_keys, contains_terms):
    for key, value in payload.items():
        if normalize_key(key) in exact_keys and value not in (None, ""):
            return str(value)

    for key, value in payload.items():
        normalized = normalize_key(key)
        if any(term in normalized for term in contains_terms) and value not in (None, ""):
            return str(value)

    return ""


def extract_weight(payload):
    return extract_number(payload, WEIGHT_KEYS, ["weight", "lbs", "pounds"])


def extract_charge(payload):
    return extract_number(payload, CHARGE_KEYS, ["charge", "amount", "cost", "freight"])


def extract_service(payload):
    return extract_text(payload, SERVICE_KEYS, ["service", "product"])


def zone_multiplier(zip_code):
    if not zip_code:
        return 1.0
    prefix = int(zip_code[:3])
    if prefix >= 900:
        return 1.18
    if prefix >= 750:
        return 1.10
    if prefix >= 500:
        return 1.04
    if prefix <= 99:
        return 1.12
    return 1.0


def service_profile(service_name):
    service = normalize_key(service_name)
    if "nextday" in service or "overnight" in service or "air1" in service:
        return 34.50, 2.55, 1.35
    if "2ndday" in service or "secondday" in service or "2day" in service:
        return 21.50, 1.65, 1.20
    if "3day" in service or "threeday" in service or "select" in service:
        return 16.25, 1.18, 1.10
    if "surepost" in service or "mail" in service:
        return 7.25, 0.54, 0.92
    if "ground" in service:
        return 10.75, 0.82, 1.0
    return 11.50, 0.90, 1.0


def has_residential_signal(payload):
    for key, value in payload.items():
        normalized = normalize_key(key)
        text = normalize_key(value)
        if "residential" in normalized and text in {"1", "true", "yes", "y", "residential"}:
            return True
        if "address" in normalized and "residential" in text:
            return True
    return False


def estimate_ups_charge(payload, weight, zip_code):
    """Estimate UPS-like billing per line when raw charge is unavailable.

    This is an operational estimate, not the official UPS tariff. It uses
    service, destination ZIP region, weight tiers, fuel, and simple surcharge
    signals so every shipment line contributes to suggested payment.
    """
    service = extract_service(payload)
    base, per_lb, service_multiplier = service_profile(service)
    billable_weight = max(float(weight or 1), 1.0)

    if billable_weight <= 10:
        weight_charge = billable_weight * per_lb
    elif billable_weight <= 50:
        weight_charge = (10 * per_lb) + ((billable_weight - 10) * per_lb * 0.82)
    else:
        weight_charge = (10 * per_lb) + (40 * per_lb * 0.82) + ((billable_weight - 50) * per_lb * 0.68)

    surcharge = 0.0
    if has_residential_signal(payload):
        surcharge += 5.35
    if billable_weight >= 50:
        surcharge += 18.0
    if billable_weight >= 70:
        surcharge += 35.0

    subtotal = (base + weight_charge + surcharge) * service_multiplier * zone_multiplier(zip_code)
    fuel_surcharge = subtotal * 0.16
    return money(subtotal + fuel_surcharge)


def money(value):
    return round(float(value or 0), 2)


def get_ups_sales_match_data(limit=250):
    conn = get_master_connection()
    cursor = conn.cursor()
    try:
        cursor.timeout = 15
    except AttributeError:
        pass
    try:
        cursor.execute(
            """
            SELECT
                TABLE_SCHEMA,
                TABLE_NAME
            FROM khPriority.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_NAME IN ('CarrierUPSRawData', 'USA_SalesAnalysis')
            """
        )
        discovered = {row.TABLE_NAME: row.TABLE_SCHEMA for row in cursor.fetchall()}
        if "CarrierUPSRawData" not in discovered or "USA_SalesAnalysis" not in discovered:
            return {
                "error": "CarrierUPSRawData or USA_SalesAnalysis table was not found.",
                "rows": [],
                "summary": {},
                "months": [],
                "warehouses": [],
                "customers": [],
            }

        ups_table = f"khPriority.[{discovered['CarrierUPSRawData']}].[CarrierUPSRawData]"
        sales_table = f"khPriority.[{discovered['USA_SalesAnalysis']}].[USA_SalesAnalysis]"
        cursor.execute(
            f"""
            SELECT TOP ({int(limit)})
                c.tracking_number,
                c.invoice_number,
                c.recipient_name,
                c.zip_code,
                c.state_code,
                c.billed_weight,
                c.charge_amount,
                CASE
                    WHEN LEN(COALESCE(c.invoice_number, '')) > 2
                    THEN LEFT(c.invoice_number, LEN(c.invoice_number) - 2)
                    ELSE c.invoice_number
                END AS matched_order_no
            FROM {ups_table} c
            WHERE NULLIF(LTRIM(RTRIM(c.invoice_number)), '') IS NOT NULL
            ORDER BY c.id DESC
            """
        )
        ups_columns = [column[0] for column in cursor.description]
        ups_rows = [dict(zip(ups_columns, row)) for row in cursor.fetchall()]

        order_numbers = sorted({
            str(row.get("matched_order_no") or "").strip()
            for row in ups_rows
            if str(row.get("matched_order_no") or "").strip()
        })
        sales_by_order = defaultdict(list)
        if order_numbers:
            placeholders = ",".join("?" for _ in order_numbers)
            cursor.execute(
                f"""
                SELECT
                    UPPER(s.OrigWhse) AS Warehouse,
                    s.CustomerDailySales,
                    s.orderNo,
                    s.Style,
                    s.Colour,
                    s.SSize,
                    SUM(s.qtySold) AS SoldQty,
                    SUM(s.salesRevenue) AS TotalValue,
                    CONVERT(CHAR(7), s.dtPeriod, 120) AS MonthYear
                FROM {sales_table} s
                WHERE s.orderNo IN ({placeholders})
                  AND s.dtPeriod >= DATEADD(YEAR, -3, GETDATE())
                GROUP BY
                    s.dtPeriod,
                    s.OrigWhse,
                    s.CustomerDailySales,
                    s.orderNo,
                    s.Style,
                    s.Colour,
                    s.SSize,
                    CONVERT(CHAR(7), s.dtPeriod, 120)
                """,
                order_numbers,
            )
            sales_columns = [column[0] for column in cursor.description]
            for sales_row in [dict(zip(sales_columns, row)) for row in cursor.fetchall()]:
                sales_by_order[str(sales_row.get("orderNo") or "").strip()].append(sales_row)

        db_rows = []
        for ups_row in ups_rows:
            matches = sales_by_order.get(str(ups_row.get("matched_order_no") or "").strip()) or [None]
            for sales_row in matches:
                combined = dict(ups_row)
                if sales_row:
                    combined.update(sales_row)
                else:
                    combined.update({
                        "Warehouse": None,
                        "CustomerDailySales": None,
                        "orderNo": None,
                        "Style": None,
                        "Colour": None,
                        "SSize": None,
                        "SoldQty": None,
                        "TotalValue": None,
                        "MonthYear": None,
                    })
                db_rows.append(combined)
    except Exception as exc:
        return {
            "error": str(exc),
            "rows": [],
            "summary": {},
            "months": [],
            "warehouses": [],
            "customers": [],
        }
    finally:
        conn.close()

    rows = []
    matched = 0
    total_value = 0.0
    total_qty = 0.0
    total_weight = 0.0
    months = set()
    warehouses = set()
    customers = set()

    for row in db_rows:
        zip_code = normalize_zip(row.get("zip_code"))
        state_code = normalize_key(row.get("state_code")).upper() if row.get("state_code") else None
        if state_code not in STATE_NAMES:
            state_code = zip_to_state(zip_code) or ""
        sales_value = parse_number(row.get("TotalValue")) or 0
        sold_qty = parse_number(row.get("SoldQty")) or 0
        weight = parse_number(row.get("billed_weight")) or 0
        charge = parse_number(row.get("charge_amount")) or 0
        is_matched = bool(row.get("orderNo"))
        if is_matched:
            matched += 1
            total_value += sales_value
            total_qty += sold_qty
        total_weight += weight
        if row.get("MonthYear"):
            months.add(row["MonthYear"])
        if row.get("Warehouse"):
            warehouses.add(row["Warehouse"])
        if row.get("CustomerDailySales"):
            customers.add(row["CustomerDailySales"])

        rows.append(
            {
                "tracking_number": row.get("tracking_number") or "",
                "invoice_number": row.get("invoice_number") or "",
                "recipient_name": row.get("recipient_name") or "",
                "zip_code": zip_code or "",
                "state": state_code,
                "state_name": STATE_NAMES.get(state_code, state_code or "Unknown"),
                "weight": round(weight, 2),
                "charge": money(charge),
                "matched_order_no": row.get("matched_order_no") or "",
                "warehouse": row.get("Warehouse") or "",
                "customer": row.get("CustomerDailySales") or "",
                "order_no": row.get("orderNo") or "",
                "style": row.get("Style") or "",
                "colour": row.get("Colour") or "",
                "size": row.get("SSize") or "",
                "sold_qty": round(sold_qty, 2),
                "total_value": money(sales_value),
                "month_year": row.get("MonthYear") or "",
                "matched": is_matched,
            }
        )

    return {
        "error": None,
        "rows": rows,
        "summary": {
            "ups_rows": len(rows),
            "matched_rows": matched,
            "missing_sales": len(rows) - matched,
            "sales_value": money(total_value),
            "sold_qty": round(total_qty, 2),
            "weight": round(total_weight, 2),
        },
        "months": sorted(months, reverse=True),
        "warehouses": sorted(warehouses),
        "customers": sorted(customers)[:250],
    }


def empty_sales_match(message=None):
    return {
        "error": message,
        "rows": [],
        "summary": {
            "ups_rows": 0,
            "matched_rows": 0,
            "missing_sales": 0,
            "sales_value": 0,
            "sold_qty": 0,
            "weight": 0,
        },
        "months": [],
        "warehouses": [],
        "customers": [],
    }


def get_ups_heatmap_data(limit=50000):
    cache_key = f"ups_heatmap:{int(limit)}"
    cached = _heatmap_cache.get(cache_key)
    if cached and (time() - cached["ts"]) < HEATMAP_CACHE_TTL_SECONDS:
        return cached["data"]

    conn = get_master_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM khPriority.INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'dbo'
              AND TABLE_NAME = 'CarrierUPSRawData'
            """
        )
        columns = {str(row.COLUMN_NAME).lower() for row in cursor.fetchall()}
        if not columns:
            grouped_rows = []
        else:
            weight_expr = "TRY_CAST(billed_weight AS DECIMAL(18, 4))" if "billed_weight" in columns else "CAST(NULL AS DECIMAL(18, 4))"
            charge_expr = "TRY_CAST(charge_amount AS DECIMAL(18, 4))" if "charge_amount" in columns else "CAST(NULL AS DECIMAL(18, 4))"
            zip_expr = "zip_code" if "zip_code" in columns else "CAST(NULL AS NVARCHAR(80))"
            state_expr = "state_code" if "state_code" in columns else "CAST(NULL AS NVARCHAR(80))"
            source_expr = "source_file" if "source_file" in columns else "CAST('Unknown' AS NVARCHAR(255))"
            order_expr = "uploaded_at DESC, id DESC" if {"uploaded_at", "id"}.issubset(columns) else "id DESC" if "id" in columns else "(SELECT NULL)"
            cursor.execute(
                f"""
                WITH BaseRows AS (
                    SELECT TOP ({int(limit)})
                        NULLIF(LTRIM(RTRIM(CAST({zip_expr} AS NVARCHAR(80)))), '') AS zip_code,
                        NULLIF(LTRIM(RTRIM(CAST({state_expr} AS NVARCHAR(80)))), '') AS state_code,
                        NULLIF(LTRIM(RTRIM(CAST({source_expr} AS NVARCHAR(255)))), '') AS source_file,
                        {weight_expr} AS billed_weight,
                        {charge_expr} AS charge_amount
                    FROM khPriority.dbo.CarrierUPSRawData
                    ORDER BY {order_expr}
                )
                SELECT
                    zip_code,
                    state_code,
                    COALESCE(source_file, 'Unknown') AS source_file,
                    COUNT(1) AS shipments,
                    SUM(CASE WHEN billed_weight IS NULL OR billed_weight <= 0 THEN 1 ELSE 0 END) AS missing_weight,
                    SUM(CASE WHEN charge_amount IS NULL THEN 1 ELSE 0 END) AS missing_charge,
                    SUM(CASE WHEN billed_weight IS NULL OR billed_weight <= 0 THEN 1 ELSE billed_weight END) AS total_weight,
                    SUM(CASE WHEN charge_amount IS NULL THEN 0 ELSE charge_amount END) AS total_charge
                FROM BaseRows
                GROUP BY zip_code, state_code, COALESCE(source_file, 'Unknown')
                """
            )
            db_columns = [column[0] for column in cursor.description]
            grouped_rows = [dict(zip(db_columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()

    zip_counts = Counter()
    zip_weights = defaultdict(float)
    zip_charges = defaultdict(float)
    zip_states = {}
    state_counts = Counter()
    state_weights = defaultdict(float)
    state_charges = defaultdict(float)
    source_counts = Counter()
    source_weights = defaultdict(float)
    missing_zip = 0
    missing_weight = 0
    missing_charge = 0
    estimated_charge_rows = 0
    raw_charge_rows = 0
    parsed_rows = 0

    for row in grouped_rows:
        shipments = int(row.get("shipments") or 0)
        parsed_rows += shipments
        zip_code = normalize_zip(row.get("zip_code"))
        if not zip_code:
            missing_zip += shipments
            continue

        weight = parse_number(row.get("total_weight")) or 0
        charge = parse_number(row.get("total_charge")) or 0
        row_missing_charge = int(row.get("missing_charge") or 0)
        missing_weight += int(row.get("missing_weight") or 0)
        missing_charge += row_missing_charge
        estimated_charge_rows += row_missing_charge
        raw_charge_rows += max(shipments - row_missing_charge, 0)

        state = normalize_key(row.get("state_code")).upper() if row.get("state_code") else None
        if state not in STATE_NAMES:
            state = zip_to_state(zip_code)
        source_file = row.get("source_file") or "Unknown"
        zip_counts[zip_code] += shipments
        zip_weights[zip_code] += weight
        zip_charges[zip_code] += charge
        source_counts[source_file] += shipments
        source_weights[source_file] += weight
        if state:
            zip_states[zip_code] = state
            state_counts[state] += shipments
            state_weights[state] += weight
            state_charges[state] += charge

    state_rows = [
        {
            "state": state,
            "state_name": STATE_NAMES.get(state, state),
            "shipments": state_counts[state],
            "weight": round(weight, 2),
            "suggested_payment": money(state_charges[state]),
            "payment_per_lb": money(state_charges[state] / weight) if weight else 0,
        }
        for state, weight in sorted(state_weights.items(), key=lambda item: item[1], reverse=True)
    ]
    top_zips = [
        {
            "zip": zip_code,
            "state": zip_states.get(zip_code) or zip_to_state(zip_code) or "Unknown",
            "state_name": STATE_NAMES.get(zip_states.get(zip_code) or zip_to_state(zip_code) or "", "Unknown"),
            "shipments": zip_counts[zip_code],
            "weight": round(weight, 2),
            "suggested_payment": money(zip_charges[zip_code]),
            "payment_per_lb": money(zip_charges[zip_code] / weight) if weight else 0,
        }
        for zip_code, weight in sorted(zip_weights.items(), key=lambda item: item[1], reverse=True)[:25]
    ]
    state_zip_details = defaultdict(list)
    for zip_code, weight in sorted(zip_weights.items(), key=lambda item: item[1], reverse=True):
        state = zip_states.get(zip_code) or zip_to_state(zip_code)
        if not state:
            continue
        if len(state_zip_details[state]) >= 8:
            continue
        state_zip_details[state].append(
            {
                "zip": zip_code,
                "shipments": zip_counts[zip_code],
                "weight": round(weight, 2),
                "suggested_payment": money(zip_charges[zip_code]),
            }
        )
    top_sources = [
        {
            "source_file": source_file,
            "shipments": source_counts[source_file],
            "weight": round(weight, 2),
        }
        for source_file, weight in sorted(source_weights.items(), key=lambda item: item[1], reverse=True)[:8]
    ]

    total_weight = sum(state_weights.values())
    suggested_payment = sum(state_charges.values())
    max_state_weight = max(state_weights.values()) if state_weights else 0
    tile_rows = []
    for state, (grid_row, grid_col) in US_TILE_POSITIONS.items():
        weight = state_weights.get(state, 0.0)
        intensity = (weight / max_state_weight) if max_state_weight else 0
        tile_rows.append({
            "state": state,
            "state_name": STATE_NAMES.get(state, state),
            "row": grid_row,
            "col": grid_col,
            "weight": round(weight, 2),
            "shipments": state_counts.get(state, 0),
            "suggested_payment": money(state_charges.get(state, 0)),
            "intensity": round(intensity, 3),
            "opacity": round(0.16 + (intensity * 0.84), 3) if weight else 0.08,
        })

    result = {
        "state_rows": state_rows,
        "tile_rows": tile_rows,
        "top_zips": top_zips,
        "top_sources": top_sources,
        "state_codes": [row["state"] for row in state_rows],
        "state_values": [row["weight"] for row in state_rows],
        "state_labels": [row["state_name"] for row in state_rows],
        "state_shipments": [row["shipments"] for row in state_rows],
        "state_payments": [row["suggested_payment"] for row in state_rows],
        "state_zip_details": dict(state_zip_details),
        "total_rows": parsed_rows,
        "parsed_rows": parsed_rows,
        "mapped_rows": sum(state_counts.values()),
        "missing_zip": missing_zip,
        "missing_weight": missing_weight,
        "missing_charge": missing_charge,
        "estimated_charge_rows": estimated_charge_rows,
        "raw_charge_rows": raw_charge_rows,
        "total_weight": round(total_weight, 2),
        "suggested_payment": money(suggested_payment),
        "avg_payment_per_lb": money(suggested_payment / total_weight) if total_weight else 0,
        "unique_zips": len(zip_counts),
        "unique_states": len(state_counts),
        "sales_match": empty_sales_match(),
    }
    _heatmap_cache[cache_key] = {"ts": time(), "data": result}
    return result
