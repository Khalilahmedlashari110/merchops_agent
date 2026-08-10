import json
import os
import re
from pathlib import Path

try:
    import anthropic
except ImportError:
    anthropic = None

from app.database.connection_manager import get_master_connection

DEFAULT_UPS_CONTRACT_PATH = (
    r"d:\Cutting-PK2(Khalil)\Daily Consumption\Ali Saab Reports\USA Daily Sales"
    r"\UPS New Files\UPS Contract\01227350_CITADEL_BRANDS__2-16-2026_8-12_AM.pdf"
)

WEEKLY_GROSS_BANDS = [
    (0.01, 8361.99),
    (8362.00, 11497.99),
    (11498.00, 14633.99),
    (14634.00, 17769.99),
    (17770.00, 27177.99),
    (27178.00, 33448.99),
    (33449.00, None),
]


def normalize_zip(value):
    match = re.search(r"\d{5}", str(value or ""))
    return match.group(0) if match else None


def normalize_zone(value):
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def parse_number(value):
    if value in (None, ""):
        return None
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def payload_value(payload, candidates):
    normalized = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in payload.items()}
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]", "", candidate.lower())
        if key in normalized and normalized[key] not in (None, ""):
            return normalized[key]
    return None


def normalize_service_name(value):
    text = str(value or "").lower()
    text = text.replace("®", "").replace("™", "")
    text = re.sub(r"\bups\b", "", text)
    text = text.replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_percent(value):
    number = parse_number(value)
    if number is None:
        return None
    return number / 100 if number > 1 else number


def parse_bool(value):
    text = str(value or "").strip().lower()
    return text in {"1", "y", "yes", "true", "electronic", "epld"}


def contract_zone_values(zone_text):
    text = str(zone_text or "")
    if "all" in text.lower():
        return list(range(2, 14))
    match = re.search(r"(\d+)\s*-\s*(\d+)", text)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        return list(range(start, end + 1))
    zone = normalize_zone(text)
    return [zone] if zone else []


def contract_weight_range(weight_text):
    text = str(weight_text or "").lower()
    if "+" in text:
        start = parse_number(text)
        return start, None
    numbers = [float(value.replace(",", "")) for value in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", text)]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return None, None


def extract_contract_rules(contract_text):
    rules = {
        "agreement_no": None,
        "initial_weekly_gross": None,
        "tier_incentives": [],
        "service_incentives": [],
        "minimum_charges": [],
        "dim_divisors": {},
        "accessorial_discounts": {},
        "pld_bonus": {},
        "rule_count": 0,
    }
    text = contract_text or ""
    if not text:
        return rules

    agreement_match = re.search(r"\bD\d{9}\b", text)
    if agreement_match:
        rules["agreement_no"] = agreement_match.group(0)

    gross_match = re.search(r"based on\s+\$?([\d,]+\.\d{2})", text, re.I)
    if gross_match:
        rules["initial_weekly_gross"] = parse_number(gross_match.group(1))

    service_line_pattern = re.compile(
        r"^(UPS[^\n]+?)\s+"
        r"(\d+\.\d+%)\s+(\d+\.\d+%)\s+(\d+\.\d+%)\s+(\d+\.\d+%)\s+"
        r"(\d+\.\d+%)\s+(\d+\.\d+%)\s+(\d+\.\d+%)$",
        re.M,
    )
    for match in service_line_pattern.finditer(text):
        service_name = match.group(1).strip()
        discounts = [parse_percent(value) for value in match.groups()[1:]]
        for band, discount in zip(WEEKLY_GROSS_BANDS, discounts):
            rules["tier_incentives"].append(
                {
                    "service": service_name,
                    "service_key": normalize_service_name(service_name),
                    "weekly_from": band[0],
                    "weekly_to": band[1],
                    "discount": discount,
                    "source": "Tier Incentives",
                }
            )

    service_blocks = [
        (
            "UPS® Ground - Commercial",
            [
                ("1 - 5 lbs", "2 - 8", "43.00%"),
                ("1 - 5 lbs", "44 - 46", "43.00%"),
                ("6 - 10", "2 - 8", "44.00%"),
                ("6 - 10", "44 - 46", "44.00%"),
                ("11 - 20", "2 - 8", "45.00%"),
                ("11 - 20", "44 - 46", "45.00%"),
                ("21 - 30", "2 - 8", "45.00%"),
                ("21 - 30", "44 - 46", "45.00%"),
                ("31+", "2 - 8", "45.00%"),
                ("31+", "44 - 46", "45.00%"),
            ],
        ),
        (
            "UPS® Ground - Residential",
            [
                ("1 - 5 lbs", "2 - 8", "31.00%"),
                ("1 - 5 lbs", "44 - 46", "31.00%"),
                ("6 - 10", "2 - 8", "36.00%"),
                ("6 - 10", "44 - 46", "36.00%"),
                ("11 - 20", "2 - 8", "41.00%"),
                ("11 - 20", "44 - 46", "41.00%"),
                ("21 - 30", "2 - 8", "42.00%"),
                ("21 - 30", "44 - 46", "42.00%"),
                ("31+", "2 - 8", "42.00%"),
                ("31+", "44 - 46", "42.00%"),
            ],
        ),
        (
            "UPS Ground Saver® - 1 lb. or greater",
            [("1 - 9 lbs", "All Zones", "20.00%")],
        ),
        (
            "UPS Ground Saver® - Less than 1 lb.",
            [("1 - 16 oz", "All Zones", "20.00%")],
        ),
    ]
    for service_name, entries in service_blocks:
        for weight_text, zone_text, discount_text in entries:
            weight_from, weight_to = contract_weight_range(weight_text)
            for zone in contract_zone_values(zone_text):
                rules["service_incentives"].append(
                    {
                        "service": service_name,
                        "service_key": normalize_service_name(service_name),
                        "zone": zone,
                        "weight_from": weight_from,
                        "weight_to": weight_to,
                        "discount": parse_percent(discount_text),
                        "source": "Service Incentives",
                    }
                )

    for service_name, divisor in re.findall(r"^(Domestic Air|Domestic Ground)\s+(\d+)$", text, re.M):
        rules["dim_divisors"][normalize_service_name(service_name)] = int(divisor)

    for line in text.splitlines():
        match = re.match(r"(.+?)\s+(Domestic(?: Air| Ground)?)\s+(\d+(?:\.\d+)?)\s*%\s+Off$", line.strip())
        if match:
            accessorial, service_group, discount = match.groups()
            key = f"{normalize_service_name(accessorial)}::{normalize_service_name(service_group)}"
            rules["accessorial_discounts"][key] = parse_percent(discount)

    for service_name, bonus in re.findall(r"^(UPS[^\n]+?)\s+(\d+(?:\.\d+)?)%$", text, re.M):
        service_key = normalize_service_name(service_name)
        if service_key:
            rules["pld_bonus"][service_key] = parse_percent(bonus)

    rules["rule_count"] = (
        len(rules["tier_incentives"])
        + len(rules["service_incentives"])
        + len(rules["minimum_charges"])
        + len(rules["dim_divisors"])
        + len(rules["accessorial_discounts"])
        + len(rules["pld_bonus"])
    )
    return rules


def service_key_matches(rule_key, service_key):
    if not rule_key or not service_key:
        return False
    return rule_key == service_key or rule_key in service_key or service_key in rule_key


def matching_contract_discount(contract_rules, service_name, zone, weight, weekly_gross=None, is_electronic_pld=True):
    service_key = normalize_service_name(service_name)
    discounts = []

    if zone is not None and weight is not None:
        for rule in contract_rules.get("service_incentives", []):
            if not service_key_matches(rule["service_key"], service_key):
                continue
            if int(zone) != int(rule["zone"]):
                continue
            if weight < (rule["weight_from"] or 0):
                continue
            if rule["weight_to"] is not None and weight > rule["weight_to"]:
                continue
            discounts.append(rule)

    weekly = weekly_gross or contract_rules.get("initial_weekly_gross")
    if weekly is not None:
        for rule in contract_rules.get("tier_incentives", []):
            if not service_key_matches(rule["service_key"], service_key):
                continue
            if weekly < rule["weekly_from"]:
                continue
            if rule["weekly_to"] is not None and weekly > rule["weekly_to"]:
                continue
            discounts.append(rule)

    if not discounts:
        return None, "No matching contract discount for service/zone/weight"

    best = max(discounts, key=lambda item: item.get("discount") or 0)
    discount = best.get("discount") or 0
    pld_bonus = 0
    for bonus_service_key, bonus in contract_rules.get("pld_bonus", {}).items():
        if service_key_matches(bonus_service_key, service_key):
            pld_bonus = bonus or 0
            break
    if not is_electronic_pld and pld_bonus:
        discount = max(0, discount - pld_bonus)

    return {
        "discount": discount,
        "base_discount": best.get("discount") or 0,
        "pld_bonus_removed": pld_bonus if not is_electronic_pld else 0,
        "source": best.get("source"),
        "service": best.get("service"),
    }, None


def contract_expected_charge(contract_rules, row_payload, service_name, zone, weight, published_charge, component_values):
    if not contract_rules.get("rule_count"):
        return None, "Contract rules were not extracted from the PDF", None
    if not service_name:
        return None, "Missing service name", None
    if zone is None:
        return None, "Missing shipment zone; exact UPS zone chart by ZIP is required", None
    if weight is None:
        return None, "Missing billed/billable weight", None
    if published_charge is None or published_charge <= 0:
        return None, "Missing published/list transportation charge from invoice", None

    is_electronic_pld = parse_bool(payload_value(row_payload, ["IsElectronicPLD", "Electronic PLD", "PLD", "EPLD"]))
    rule, error = matching_contract_discount(
        contract_rules,
        service_name=service_name,
        zone=zone,
        weight=weight,
        is_electronic_pld=is_electronic_pld or payload_value(row_payload, ["IsElectronicPLD", "Electronic PLD", "PLD", "EPLD"]) is None,
    )
    if error:
        return None, error, None

    expected_transport = round(published_charge * (1 - rule["discount"]), 4)
    fuel = component_values.get("fuel_surcharge") or 0
    residential = component_values.get("residential_surcharge") or 0
    other = component_values.get("other_accessorial_charge") or 0
    expected_total = expected_transport + fuel + residential + other
    detail = {
        "discount": rule["discount"],
        "discount_source": rule["source"],
        "contract_service": rule["service"],
        "published_charge": published_charge,
        "expected_transport": expected_transport,
        "component_note": "Fuel/accessorial components are passed through unless published surcharge base values are available.",
    }
    return round(expected_total, 4), "Expected charge calculated from contract discount and invoice published charge", detail


def expected_charge_from_payload(payload):
    return parse_number(
        payload_value(
            payload,
            [
                "Expected Charge",
                "ExpectedCharge",
                "Contract Charge",
                "ContractCharge",
                "Contract Rate",
                "ContractRate",
                "Suggested Payment",
                "SuggestedPayment",
                "Expected Payment",
                "ExpectedPayment",
            ],
        )
    )


def billing_status(actual_charge, expected_charge):
    if actual_charge is None:
        return "Need Billing Match", None, "No actual billing row matched this tracking ID"
    if actual_charge <= 0:
        return "Skipped Zero", None, "Zero or blank billed amount skipped for this audit run"
    if expected_charge is None:
        return "Need Contract Rate", None, "No contract expected charge/rate available for this tracking ID"

    difference = actual_charge - expected_charge
    if -0.50 <= difference <= 0.50:
        return "Correct", difference, "Actual billed charge is within +/- $0.50 of expected contract charge"
    if difference > 0.50:
        return "Overbilled", difference, "Actual billed charge is higher than expected contract charge"
    return "Underbilled", difference, "Actual billed charge is lower than expected contract charge"


def estimated_zone_from_zip(origin_zip, destination_zip):
    """Approximate UPS zone from ZIP prefix distance.

    Exact UPS zones require the UPS zone chart for the shipper origin.
    This creates a first-pass audit signal so suspicious records can be reviewed.
    """
    origin = normalize_zip(origin_zip)
    destination = normalize_zip(destination_zip)
    if not origin or not destination:
        return None

    distance = abs(int(origin[:3]) - int(destination[:3]))
    if distance <= 35:
        return 2
    if distance <= 95:
        return 3
    if distance <= 180:
        return 4
    if distance <= 300:
        return 5
    if distance <= 450:
        return 6
    if distance <= 650:
        return 7
    return 8


def read_contract_text(path, max_chars=80000):
    if not path:
        return "", None

    pdf_path = Path(path).expanduser()
    try:
        exists = pdf_path.exists()
    except OSError as exc:
        return "", f"Contract file cannot be accessed: {path}. {exc}"

    if not exists:
        return "", f"Contract file not found: {path}"

    try:
        import pdfplumber

        parts = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[:20]:
                parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
        return text[:max_chars], None
    except Exception as first_error:
        try:
            import fitz

            parts = []
            with fitz.open(str(pdf_path)) as doc:
                for page in doc[:20]:
                    parts.append(page.get_text("text") or "")
            text = "\n".join(parts).strip()
            return text[:max_chars], None
        except Exception as second_error:
            return "", f"Could not read contract PDF. {first_error}; {second_error}"


def load_raw_audit_rows(limit=250, origin_zip="", contract_rules=None):
    conn = get_master_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT
                OBJECT_ID('khPriority.dbo.CarrierUPSRawData', 'U') AS raw_table_id,
                OBJECT_ID('khPriority.dbo.CarrierUPSActualBilling', 'U') AS billing_table_id
            """
        )
        table_state = cursor.fetchone()
        if not table_state or not table_state.raw_table_id:
            db_rows = []
        elif table_state.billing_table_id:
            cursor.execute(
                f"""
                SELECT TOP ({int(limit)})
                    r.id,
                    r.tracking_number,
                    r.zip_code,
                    r.state_code,
                    r.zone,
                    r.billed_weight,
                    r.service_level AS manifest_service_level,
                    r.charge_amount,
                    r.source_file,
                    r.raw_payload,
                    b.invoice_number,
                    b.invoice_date,
                    b.service_level AS billing_service_level,
                    b.zone AS billing_zone,
                    b.billed_weight AS billing_weight,
                    b.published_charge,
                    b.transportation_charge,
                    b.fuel_surcharge,
                    b.residential_surcharge,
                    b.other_accessorial_charge,
                    b.total_billed_charge,
                    b.raw_Charge_Total,
                    b.raw_payload AS billing_raw_payload,
                    b.source_file AS billing_source_file
                FROM khPriority.dbo.CarrierUPSRawData r
                OUTER APPLY (
                    SELECT TOP 1
                        ab.invoice_number,
                        ab.invoice_date,
                        ab.service_level,
                        ab.zone,
                        ab.billed_weight,
                        ab.published_charge,
                        ab.transportation_charge,
                        ab.fuel_surcharge,
                        ab.residential_surcharge,
                        ab.other_accessorial_charge,
                        ab.total_billed_charge,
                        ab.raw_Charge_Total,
                        ab.raw_payload,
                        ab.source_file
                    FROM khPriority.dbo.CarrierUPSActualBilling ab
                    WHERE NULLIF(LTRIM(RTRIM(r.tracking_number)), '') IS NOT NULL
                      AND NULLIF(LTRIM(RTRIM(COALESCE(NULLIF(ab.tracking_number, ''), NULLIF(ab.raw_Tracking_No, '')))), '') IS NOT NULL
                      AND UPPER(REPLACE(LTRIM(RTRIM(COALESCE(NULLIF(ab.tracking_number, ''), NULLIF(ab.raw_Tracking_No, '')))), ' ', ''))
                        = UPPER(REPLACE(LTRIM(RTRIM(r.tracking_number)), ' ', ''))
                    ORDER BY ab.id DESC
                ) b
                ORDER BY r.id DESC
                """
            )
            db_rows = cursor.fetchall()
        else:
            cursor.execute(
                f"""
                SELECT TOP ({int(limit)})
                    id,
                    tracking_number,
                    zip_code,
                    state_code,
                    zone,
                    billed_weight,
                    service_level AS manifest_service_level,
                    charge_amount,
                    source_file,
                    raw_payload,
                    CAST(NULL AS NVARCHAR(255)) AS invoice_number,
                    CAST(NULL AS NVARCHAR(120)) AS invoice_date,
                    CAST(NULL AS NVARCHAR(255)) AS billing_service_level,
                    CAST(NULL AS NVARCHAR(80)) AS billing_zone,
                    CAST(NULL AS DECIMAL(18, 4)) AS billing_weight,
                    CAST(NULL AS DECIMAL(18, 4)) AS published_charge,
                    CAST(NULL AS DECIMAL(18, 4)) AS transportation_charge,
                    CAST(NULL AS DECIMAL(18, 4)) AS fuel_surcharge,
                    CAST(NULL AS DECIMAL(18, 4)) AS residential_surcharge,
                    CAST(NULL AS DECIMAL(18, 4)) AS other_accessorial_charge,
                    CAST(NULL AS DECIMAL(18, 4)) AS total_billed_charge,
                    CAST(NULL AS NVARCHAR(MAX)) AS raw_Charge_Total,
                    CAST(NULL AS NVARCHAR(MAX)) AS billing_raw_payload,
                    CAST(NULL AS NVARCHAR(500)) AS billing_source_file
                FROM khPriority.dbo.CarrierUPSRawData
                ORDER BY id DESC
                """
            )
            db_rows = cursor.fetchall()
    finally:
        conn.close()

    rows = []
    counters = {
        "total": 0,
        "ok": 0,
        "billed_tested": 0,
        "correct": 0,
        "overbilled": 0,
        "underbilled": 0,
        "need_contract_rate": 0,
        "need_billing_match": 0,
        "skipped_zero": 0,
        "billing_exceptions": 0,
        "zone_review": 0,
        "missing_zip": 0,
        "missing_weight": 0,
        "missing_charge": 0,
    }

    for row in db_rows:
        try:
            payload = json.loads(row.raw_payload or "{}")
        except Exception:
            payload = {}
        try:
            billing_payload = json.loads(getattr(row, "billing_raw_payload", None) or "{}")
        except Exception:
            billing_payload = {}
        merged_payload = {**payload, **billing_payload}

        tracking = row.tracking_number or payload_value(payload, ["Tracking Number", "Tracking No", "Tracking"])
        destination_zip = normalize_zip(row.zip_code) or normalize_zip(payload_value(payload, ["ZIP", "Zip Code", "Postal Code", "Destination ZIP"]))
        actual_zone = normalize_zone(getattr(row, "billing_zone", None) or row.zone or payload_value(merged_payload, ["Zone", "UPS Zone"]))
        expected_zone = estimated_zone_from_zip(origin_zip, destination_zip)
        contract_zone = actual_zone or expected_zone
        service_name = (
            getattr(row, "billing_service_level", None)
            or getattr(row, "manifest_service_level", None)
            or payload_value(merged_payload, ["Service", "Service Level", "ServiceType", "UPS Service"])
        )
        weight = parse_number(getattr(row, "billing_weight", None))
        if weight is None:
            weight = parse_number(row.billed_weight)
        if weight is None:
            weight = parse_number(payload_value(merged_payload, ["Billed Weight", "Weight", "Actual Weight"]))

        billing_charge = parse_number(getattr(row, "total_billed_charge", None))
        if billing_charge is None:
            billing_charge = parse_number(getattr(row, "raw_Charge_Total", None))
        charge = billing_charge
        published_charge = parse_number(getattr(row, "published_charge", None))
        if published_charge is None:
            published_charge = parse_number(
                payload_value(
                    merged_payload,
                    ["Published Charge", "PublishedCharge", "Published Rate", "List Charge", "Transportation Published Charge"],
                )
            )
        component_values = {
            "transportation_charge": parse_number(getattr(row, "transportation_charge", None)),
            "fuel_surcharge": parse_number(getattr(row, "fuel_surcharge", None)),
            "residential_surcharge": parse_number(getattr(row, "residential_surcharge", None)),
            "other_accessorial_charge": parse_number(getattr(row, "other_accessorial_charge", None)),
        }

        status = "OK"
        reasons = []
        if not destination_zip:
            status = "Need Review"
            reasons.append("Missing destination ZIP")
            counters["missing_zip"] += 1
        if not weight:
            status = "Need Review"
            reasons.append("Missing billed weight")
            counters["missing_weight"] += 1
        if charge is None:
            status = "Need Review"
            reasons.append("Missing billed charge")
            counters["missing_charge"] += 1

        expected_charge, contract_reason, contract_detail = contract_expected_charge(
            contract_rules or {},
            merged_payload,
            service_name,
            contract_zone,
            weight,
            published_charge,
            component_values,
        )
        if expected_charge is None:
            expected_charge = expected_charge_from_payload(merged_payload)
            contract_detail = None
            if expected_charge is not None:
                contract_reason = "Expected charge found in uploaded payload"

        bill_status, difference, bill_reason = billing_status(charge, expected_charge)
        if expected_charge is None and bill_status == "Need Contract Rate" and contract_reason:
            bill_reason = contract_reason
        if bill_status == "Skipped Zero":
            counters["skipped_zero"] += 1
        else:
            counters["billed_tested"] += 1
            if bill_status == "Correct":
                counters["correct"] += 1
            elif bill_status == "Overbilled":
                counters["overbilled"] += 1
                counters["billing_exceptions"] += 1
            elif bill_status == "Underbilled":
                counters["underbilled"] += 1
                counters["billing_exceptions"] += 1
            elif bill_status == "Need Contract Rate":
                counters["need_contract_rate"] += 1
                counters["billing_exceptions"] += 1
            elif bill_status == "Need Billing Match":
                counters["need_billing_match"] += 1
                counters["billing_exceptions"] += 1

        if actual_zone and expected_zone and actual_zone != expected_zone:
            status = "Zone Review"
            reasons.append(f"Entered zone {actual_zone} differs from estimated zone {expected_zone}")
            counters["zone_review"] += 1
        elif status == "OK":
            counters["ok"] += 1

        counters["total"] += 1
        rows.append(
            {
                "id": row.id,
                "tracking_number": tracking or "",
                "zip_code": destination_zip or "",
                "state_code": row.state_code or "",
                "service_name": service_name or "",
                "actual_zone": actual_zone,
                "estimated_zone": expected_zone,
                "contract_zone": contract_zone,
                "billed_weight": weight,
                "published_charge": published_charge,
                "contract_discount": contract_detail.get("discount") if contract_detail else None,
                "discount_source": contract_detail.get("discount_source") if contract_detail else "",
                "charge_amount": charge,
                "expected_charge": expected_charge,
                "difference": difference,
                "billing_status": bill_status,
                "billing_reason": bill_reason,
                "invoice_number": getattr(row, "invoice_number", None) or "",
                "invoice_date": getattr(row, "invoice_date", None) or "",
                "billing_source_file": getattr(row, "billing_source_file", None) or "",
                "source_file": row.source_file or "Unknown",
                "status": status,
                "reason": "; ".join(reasons) if reasons else "Basic ZIP/zone/weight check passed",
            }
        )

    return counters, rows


def anthropic_audit_summary(contract_text, counters, rows, origin_zip):
    if anthropic is None:
        return "Anthropic package is not installed. Deterministic billing checks are shown below."

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "Anthropic API key is not configured. Deterministic audit checks are shown below."

    sample_rows = rows[:40]
    prompt = {
        "origin_zip": origin_zip,
        "summary": counters,
        "sample_exceptions": [row for row in sample_rows if row["billing_status"] not in {"Correct", "Skipped Zero"}][:25],
        "contract_excerpt": contract_text[:12000],
    }

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=os.environ.get("ANTHROPIC_AUDIT_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=900,
        temperature=0.1,
        system=(
            "You are a professional UPS billing audit assistant. "
            "Use deterministic data as truth. Do not invent contract rates. "
            "If exact UPS zone chart or contract rate table is missing, say what is needed."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    "Review this UPS billing audit. Focus first on whether charged bills are correct. "
                    "Zero billed rows are intentionally skipped. If expected contract rates are missing, "
                    "explain that exact correctness needs the contract rate/zone table and list next steps.\n\n"
                    + json.dumps(prompt, default=str)
                ),
            }
        ],
    )
    return "\n".join(block.text for block in response.content if getattr(block, "type", "") == "text")


def run_smart_audit(origin_zip="", contract_path="", limit=250, use_ai=False):
    contract_path = contract_path or DEFAULT_UPS_CONTRACT_PATH
    contract_text, contract_error = read_contract_text(contract_path)
    contract_rules = extract_contract_rules(contract_text)
    counters, rows = load_raw_audit_rows(limit=limit, origin_zip=origin_zip, contract_rules=contract_rules)
    ai_summary = ""
    ai_error = None

    if use_ai:
        try:
            ai_summary = anthropic_audit_summary(contract_text, counters, rows, origin_zip)
        except Exception as exc:
            ai_error = str(exc)

    return {
        "origin_zip": origin_zip,
        "contract_path": contract_path,
        "contract_error": contract_error,
        "contract_loaded": bool(contract_text),
        "contract_rules": contract_rules,
        "counters": counters,
        "rows": rows,
        "billing_exceptions": [
            row for row in rows
            if row["billing_status"] not in {"Correct", "Skipped Zero"}
        ],
        "ai_summary": ai_summary,
        "ai_error": ai_error,
    }
