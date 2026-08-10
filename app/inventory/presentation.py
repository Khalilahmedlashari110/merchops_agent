import os
import re
from typing import Dict, List, Tuple

import pandas as pd


EXPECTED_COLUMNS = {
    "distributor": ["distributor", "buyer", "customer", "account"],
    "brand": ["brand", "buyerabrv"],
    "style": ["style", "stylecode"],
    "colour": ["colour", "color"],
    "ssize": ["ssize", "size", "ordsize"],
    "sku": ["sku", "item", "navcode", "productarticle"],
    "stockqty": ["stockqty", "stock", "lateststock", "physicalstock", "physical_stock"],
    "pipelineqty": ["pipelineqty", "committed", "committedqty", "latestcmtqty", "pipeline"],
    "availableqty": ["availableqty", "available"],
    "intransitqty": ["intransitqty", "intransit", "ship_qty", "shipmentqty"],
    "avgmonthlysales6m": ["avgmonthlysales6m", "avg6m", "monthlyavg", "monthly_sales_avg", "avg_sales_6m"],
    "stockreqmonths": ["stockreqmonths", "stockmonths", "requiredmonths", "reqmonths"],
    "reqstock": ["reqstock", "requiredstock", "required_stock"],
    "coveragemonths": ["coveragemonths", "coverage_months"],
    "coveragepct": ["coveragepct", "coverage", "coverage_pct"],
    "reqneworderqty": ["reqneworderqty", "neworder", "new_order_required", "requiredneworderqty"],
}


DISPLAY_COLUMN_ORDER = [
    "Distributor",
    "Brand",
    "Style",
    "Colour",
    "SSize",
    "SKU",
    "StockQty",
    "PipelineQty",
    "AvailableQty",
    "InTransitQty",
    "AvgMonthlySales6M",
    "StockReqMonths",
    "ReqStock",
    "CoveragePct",
    "CoveragePctInclInTransit",
    "CoverageMonths",
    "ReqNewOrderQty",
    "RiskStatus",
]


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).strip().lower())


def detect_column_mapping(columns: List[str]) -> Dict[str, str]:
    normalized_to_original = {_normalize_name(c): c for c in columns}
    mapping = {}

    for target, aliases in EXPECTED_COLUMNS.items():
        for alias in aliases:
            norm_alias = _normalize_name(alias)
            if norm_alias in normalized_to_original:
                mapping[target] = normalized_to_original[norm_alias]
                break

    return mapping


def read_uploaded_inventory(file_path: str) -> pd.DataFrame:
    ext = os.path.splitext(file_path)[1].lower()

    if ext in [".xlsx", ".xls"]:
        return pd.read_excel(file_path)
    elif ext == ".csv":
        return pd.read_csv(file_path)
    else:
        raise ValueError("Unsupported file format. Please upload Excel or CSV.")


def to_float(value) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def safe_divide(a: float, b: float) -> float:
    if not b:
        return 0.0
    return a / b


def cap_coverage(value: float) -> float:
    value = to_float(value)
    if value < 0:
        return 0.0
    if value > 100:
        return 100.0
    return round(value, 2)


def get_risk_status(coverage_pct: float, req_new_order_qty: float, available_qty: float) -> str:
    if available_qty <= 0:
        return "Out of Stock"
    if coverage_pct <= 20:
        return "Critical"
    if coverage_pct < 60:
        return "High Risk"
    if coverage_pct < 100:
        return "Low Coverage"
    if req_new_order_qty > 0:
        return "New Order Required"
    return "Safe"


def standardize_inventory_dataframe(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str]]:
    df = df.copy()
    mapping = detect_column_mapping(list(df.columns))

    standardized = pd.DataFrame()

    standardized["Distributor"] = df[mapping["distributor"]] if "distributor" in mapping else ""
    standardized["Brand"] = df[mapping["brand"]] if "brand" in mapping else ""
    standardized["Style"] = df[mapping["style"]] if "style" in mapping else ""
    standardized["Colour"] = df[mapping["colour"]] if "colour" in mapping else ""
    standardized["SSize"] = df[mapping["ssize"]] if "ssize" in mapping else ""
    standardized["SKU"] = df[mapping["sku"]] if "sku" in mapping else ""

    standardized["StockQty"] = df[mapping["stockqty"]].apply(to_float) if "stockqty" in mapping else 0.0
    standardized["PipelineQty"] = df[mapping["pipelineqty"]].apply(to_float) if "pipelineqty" in mapping else 0.0
    standardized["InTransitQty"] = df[mapping["intransitqty"]].apply(to_float) if "intransitqty" in mapping else 0.0
    standardized["AvgMonthlySales6M"] = df[mapping["avgmonthlysales6m"]].apply(to_float) if "avgmonthlysales6m" in mapping else 0.0
    standardized["StockReqMonths"] = df[mapping["stockreqmonths"]].apply(to_float) if "stockreqmonths" in mapping else 6.0

    if "availableqty" in mapping:
        standardized["AvailableQty"] = df[mapping["availableqty"]].apply(to_float)
    else:
        standardized["AvailableQty"] = standardized["StockQty"] + standardized["PipelineQty"]

    if "reqstock" in mapping:
        standardized["ReqStock"] = df[mapping["reqstock"]].apply(to_float)
    else:
        standardized["ReqStock"] = standardized["AvgMonthlySales6M"] * standardized["StockReqMonths"]

    if "coveragemonths" in mapping:
        standardized["CoverageMonths"] = df[mapping["coveragemonths"]].apply(to_float)
    else:
        standardized["CoverageMonths"] = standardized.apply(
            lambda r: round(safe_divide(r["AvailableQty"], r["AvgMonthlySales6M"]), 2)
            if r["AvgMonthlySales6M"] > 0 else 0,
            axis=1
        )

    if "coveragepct" in mapping:
        standardized["CoveragePct"] = df[mapping["coveragepct"]].apply(to_float)
    else:
        standardized["CoveragePct"] = standardized.apply(
            lambda r: round(safe_divide(r["AvailableQty"], r["ReqStock"]) * 100, 2)
            if r["ReqStock"] > 0 else 0,
            axis=1
        )

    standardized["CoveragePct"] = standardized["CoveragePct"].apply(cap_coverage)

    standardized["CoveragePctInclInTransit"] = standardized.apply(
        lambda r: round(
            safe_divide((to_float(r["AvailableQty"]) + to_float(r["InTransitQty"])), to_float(r["ReqStock"])) * 100,
            2
        ) if to_float(r["ReqStock"]) > 0 else 0,
        axis=1
    )
    standardized["CoveragePctInclInTransit"] = standardized["CoveragePctInclInTransit"].apply(cap_coverage)

    if "reqneworderqty" in mapping:
        standardized["ReqNewOrderQty"] = df[mapping["reqneworderqty"]].apply(to_float)
    else:
        standardized["ReqNewOrderQty"] = standardized.apply(
            lambda r: max(0.0, round(r["ReqStock"] - (r["AvailableQty"] + r["InTransitQty"]), 2)),
            axis=1
        )

    standardized["RiskStatus"] = standardized.apply(
        lambda r: get_risk_status(
            coverage_pct=to_float(r["CoveragePct"]),
            req_new_order_qty=to_float(r["ReqNewOrderQty"]),
            available_qty=to_float(r["AvailableQty"])
        ),
        axis=1
    )

    standardized = standardized[DISPLAY_COLUMN_ORDER]
    return standardized, mapping


def dataframe_to_records(df: pd.DataFrame) -> List[dict]:
    records = df.to_dict(orient="records")
    cleaned = []

    for row in records:
        clean_row = {}
        for k, v in row.items():
            if pd.isna(v):
                clean_row[k] = ""
            elif isinstance(v, float):
                clean_row[k] = round(v, 2)
            else:
                clean_row[k] = v
        cleaned.append(clean_row)

    return cleaned


def get_presentation_summary(rows: List[dict]) -> dict:
    return {
        "total_rows": len(rows),
        "critical_count": sum(1 for r in rows if r["RiskStatus"] == "Critical"),
        "high_risk_count": sum(1 for r in rows if r["RiskStatus"] == "High Risk"),
        "out_of_stock_count": sum(1 for r in rows if r["RiskStatus"] == "Out of Stock"),
        "new_order_count": sum(1 for r in rows if float(r.get("ReqNewOrderQty", 0) or 0) > 0),
    }


def apply_presentation_filters(rows: List[dict], distributor="", brand="", style="", risk="") -> List[dict]:
    filtered = rows

    if distributor:
        filtered = [r for r in filtered if str(r.get("Distributor", "")).lower() == distributor.lower()]

    if brand:
        filtered = [r for r in filtered if str(r.get("Brand", "")).lower() == brand.lower()]

    if style:
        filtered = [r for r in filtered if str(r.get("Style", "")).lower() == style.lower()]

    if risk:
        filtered = [r for r in filtered if str(r.get("RiskStatus", "")).lower() == risk.lower()]

    return filtered