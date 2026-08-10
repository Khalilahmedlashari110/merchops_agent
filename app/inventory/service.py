import json
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path
from time import time

from app.database.connection_manager import get_master_connection


CITADEL_DISTRIBUTOR = "Citadel Brands LLC"
SCORECARD_CACHE_TTL_SECONDS = 300
REQUIREMENT_SETTINGS_PATH = Path(__file__).with_name("requirement_settings.json")
_scorecard_cache = {}


def get_default_anchor_date():
    today = date.today()
    return date(today.year, today.month, 1)


def _setting_key(distributor, brand):
    return (
        str(distributor or "").strip().lower(),
        str(brand or "").strip().lower(),
    )


def _load_requirement_payload():
    if not REQUIREMENT_SETTINGS_PATH.exists():
        return {"settings": []}

    try:
        with REQUIREMENT_SETTINGS_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {"settings": []}

    if not isinstance(payload, dict):
        return {"settings": []}

    settings = payload.get("settings")
    if not isinstance(settings, list):
        payload["settings"] = []
    return payload


def _save_requirement_payload(payload):
    REQUIREMENT_SETTINGS_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def get_requirement_settings(distributor=None):
    settings = _load_requirement_payload().get("settings", [])
    if distributor:
        settings = [
            item for item in settings
            if str(item.get("Distributor") or "").lower() == str(distributor).lower()
        ]

    return sorted(
        settings,
        key=lambda item: (
            str(item.get("Distributor") or ""),
            str(item.get("Brand") or ""),
        ),
    )


def save_requirement_setting(distributor, brand, requirement_months):
    distributor = str(distributor or "").strip()
    brand = str(brand or "").strip()
    months = _num(requirement_months)

    if not distributor:
        raise ValueError("Distributor is required.")
    if not brand:
        raise ValueError("Brand is required.")
    if months <= 0 or months > 24:
        raise ValueError("Requirement months must be between 0 and 24.")

    payload = _load_requirement_payload()
    settings = payload.get("settings", [])
    key = _setting_key(distributor, brand)
    saved = {
        "Distributor": distributor,
        "Brand": brand,
        "RequirementMonths": months,
        "UpdatedAt": date.today().isoformat(),
    }

    replaced = False
    for index, item in enumerate(settings):
        if _setting_key(item.get("Distributor"), item.get("Brand")) == key:
            settings[index] = saved
            replaced = True
            break

    if not replaced:
        settings.append(saved)

    payload["settings"] = settings
    _save_requirement_payload(payload)
    return saved


def delete_requirement_setting(distributor, brand):
    payload = _load_requirement_payload()
    key = _setting_key(distributor, brand)
    payload["settings"] = [
        item for item in payload.get("settings", [])
        if _setting_key(item.get("Distributor"), item.get("Brand")) != key
    ]
    _save_requirement_payload(payload)


def build_requirement_brand_options(rows):
    grouped = defaultdict(list)
    for row in rows or []:
        grouped[str(row.get("Brand") or "Unknown")].append(row)

    options = []
    for brand, items in grouped.items():
        db_months = [
            _num(item.get("StockReqMonths"))
            for item in items
            if _num(item.get("StockReqMonths")) > 0
        ]
        avg_db_months = round(sum(db_months) / len(db_months), 1) if db_months else 0
        options.append({
            "Brand": brand,
            "Rows": len(items),
            "AvgDbMonths": avg_db_months,
        })

    return sorted(options, key=lambda item: item["Brand"])


SCORECARD_QUERY = """
WITH SalesWindow AS (
    SELECT
        st.Buyer COLLATE SQL_Latin1_General_CP1_CI_AS AS Distributor,
        sm.BUYERABRV COLLATE SQL_Latin1_General_CP1_CI_AS AS Brand,
        sm.Style,
        sm.Colour,
        sm.SSize,
        st.Item COLLATE SQL_Latin1_General_CP1_CI_AS AS SKU,
        DATEFROMPARTS(
            st.dtYear,
            CASE UPPER(LTRIM(RTRIM(st.dtMonth)))
                WHEN 'JAN' THEN 1 WHEN 'FEB' THEN 2 WHEN 'MAR' THEN 3
                WHEN 'APR' THEN 4 WHEN 'MAY' THEN 5 WHEN 'JUN' THEN 6
                WHEN 'JUL' THEN 7 WHEN 'AUG' THEN 8 WHEN 'SEP' THEN 9
                WHEN 'OCT' THEN 10 WHEN 'NOV' THEN 11 WHEN 'DEC' THEN 12
                ELSE NULL
            END, 1
        ) AS dtSales,
        st.SellQuantity
    FROM dbMerchandising.dbo.tblCustomerSell AS st
    INNER JOIN Proline.dbo.MerStyleMasterDetail AS sm
        ON st.Item COLLATE SQL_Latin1_General_CP1_CI_AS
         = sm.NAVCode COLLATE SQL_Latin1_General_CP1_CI_AS
       AND sm.BodyCombo IN ('Body Fabric','Combo A')
       AND sm.ColourDiscontinue = 0
    WHERE DATEFROMPARTS(
            st.dtYear,
            CASE UPPER(LTRIM(RTRIM(st.dtMonth)))
                WHEN 'JAN' THEN 1 WHEN 'FEB' THEN 2 WHEN 'MAR' THEN 3
                WHEN 'APR' THEN 4 WHEN 'MAY' THEN 5 WHEN 'JUN' THEN 6
                WHEN 'JUL' THEN 7 WHEN 'AUG' THEN 8 WHEN 'SEP' THEN 9
                WHEN 'OCT' THEN 10 WHEN 'NOV' THEN 11 WHEN 'DEC' THEN 12
                ELSE NULL
            END, 1
        ) >= DATEADD(YEAR, -1, ?)
      AND DATEFROMPARTS(
            st.dtYear,
            CASE UPPER(LTRIM(RTRIM(st.dtMonth)))
                WHEN 'JAN' THEN 1 WHEN 'FEB' THEN 2 WHEN 'MAR' THEN 3
                WHEN 'APR' THEN 4 WHEN 'MAY' THEN 5 WHEN 'JUN' THEN 6
                WHEN 'JUL' THEN 7 WHEN 'AUG' THEN 8 WHEN 'SEP' THEN 9
                WHEN 'OCT' THEN 10 WHEN 'NOV' THEN 11 WHEN 'DEC' THEN 12
                ELSE NULL
            END, 1
        ) < ?
      AND st.Buyer = ?

    UNION ALL

    SELECT
        'AWDis B.V.' AS Distributor,
        sm.BUYERABRV COLLATE SQL_Latin1_General_CP1_CI_AS AS Brand,
        sm.Style,
        sm.Colour,
        sm.SSize,
        st.Item COLLATE SQL_Latin1_General_CP1_CI_AS AS SKU,
        DATEFROMPARTS(
            st.dtYear,
            CASE UPPER(LTRIM(RTRIM(st.dtMonth)))
                WHEN 'JAN' THEN 1 WHEN 'FEB' THEN 2 WHEN 'MAR' THEN 3
                WHEN 'APR' THEN 4 WHEN 'MAY' THEN 5 WHEN 'JUN' THEN 6
                WHEN 'JUL' THEN 7 WHEN 'AUG' THEN 8 WHEN 'SEP' THEN 9
                WHEN 'OCT' THEN 10 WHEN 'NOV' THEN 11 WHEN 'DEC' THEN 12
                ELSE NULL
            END, 1
        ) AS dtSales,
        st.SellQuantity
    FROM dbMerchandising.dbo.tblCustomerSell AS st
    INNER JOIN Proline.dbo.MerStyleMasterDetail AS sm
        ON st.Item COLLATE SQL_Latin1_General_CP1_CI_AS
         = sm.NAVCode COLLATE SQL_Latin1_General_CP1_CI_AS
       AND sm.BodyCombo IN ('Body Fabric','Combo A')
       AND sm.ColourDiscontinue = 0
    WHERE DATEFROMPARTS(
            st.dtYear,
            CASE UPPER(LTRIM(RTRIM(st.dtMonth)))
                WHEN 'JAN' THEN 1 WHEN 'FEB' THEN 2 WHEN 'MAR' THEN 3
                WHEN 'APR' THEN 4 WHEN 'MAY' THEN 5 WHEN 'JUN' THEN 6
                WHEN 'JUL' THEN 7 WHEN 'AUG' THEN 8 WHEN 'SEP' THEN 9
                WHEN 'OCT' THEN 10 WHEN 'NOV' THEN 11 WHEN 'DEC' THEN 12
                ELSE NULL
            END, 1
        ) >= DATEADD(YEAR, -1, ?)
      AND DATEFROMPARTS(
            st.dtYear,
            CASE UPPER(LTRIM(RTRIM(st.dtMonth)))
                WHEN 'JAN' THEN 1 WHEN 'FEB' THEN 2 WHEN 'MAR' THEN 3
                WHEN 'APR' THEN 4 WHEN 'MAY' THEN 5 WHEN 'JUN' THEN 6
                WHEN 'JUL' THEN 7 WHEN 'AUG' THEN 8 WHEN 'SEP' THEN 9
                WHEN 'OCT' THEN 10 WHEN 'NOV' THEN 11 WHEN 'DEC' THEN 12
                ELSE NULL
            END, 1
        ) < ?
      AND 1 = 0
      AND sm.BUYERABRV IN ('AWDIS - JH','AWDIS ACADEMY','PRO RTX','AWDIS - JCA','AWDIS - JHA','AWDIS - JTA','WOODBROOK - WBA')
      AND st.Buyer IN ('Camac','Imbretex','L Shop','UTT')
),
A4Sales AS (
    SELECT
        navCode,
        SUM(qtySold) AS qtySold,
        dtPeriod
    FROM dbMerchandising.dbo.tblCustomerSales_USA s
    LEFT OUTER JOIN dbMerchandising.dbo.tblCrossRef c
        ON s.itemNumber = c.refCode
       AND c.Distributor = 'Citadel Brands LLC'
    WHERE customerName LIKE '%A4%'
      AND LEFT(orderNo,2) = 'A4'
      AND navCode IS NOT NULL
    GROUP BY navCode, dtPeriod
),
MonthlySales AS (
    SELECT
        Distributor, Brand, Style, Colour, SSize, SKU,
        DATEFROMPARTS(YEAR(dtSales), MONTH(dtSales), 1) AS MonthStart,
        SUM(SellQuantity) - ISNULL(A4Sales.qtySold, 0) AS SalesQty
    FROM SalesWindow
    LEFT JOIN A4Sales
      ON SalesWindow.SKU = A4Sales.navCode COLLATE SQL_Latin1_General_CP1_CI_AS
     AND DATEFROMPARTS(YEAR(SalesWindow.dtSales), MONTH(SalesWindow.dtSales), 1)
      = DATEFROMPARTS(YEAR(A4Sales.dtPeriod), MONTH(A4Sales.dtPeriod), 1)
    GROUP BY Distributor, Brand, Style, Colour, SSize, SKU,
             DATEFROMPARTS(YEAR(dtSales), MONTH(dtSales), 1),
             ISNULL(A4Sales.qtySold, 0)
),
SalesByMonth AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY Distributor, SKU ORDER BY MonthStart ASC) AS MonthRank
    FROM MonthlySales
),
Sales6 AS (
    SELECT * FROM SalesByMonth WHERE MonthRank <= 6
),
SalesAvg AS (
    SELECT
        Distributor, Brand, Style, Colour, SSize, SKU,
        COUNT(*) AS MonthsUsed,
        SUM(SalesQty) AS Sales6M,
        CAST(SUM(SalesQty) * 1.0 / NULLIF(COUNT(*),0) AS DECIMAL(18,2)) AS AvgMonthlySales6M
    FROM Sales6
    GROUP BY Distributor, Brand, Style, Colour, SSize, SKU
),
inTransit AS (
    SELECT
        ord.Style,
        ord.Colour,
        ord.OrdSize AS Size,
        inv.Distributor,
        ord.NAVCode,
        SUM(ord.ShipmentQty) AS Ship_Qty
    FROM Proline.dbo.Exp_PackingList_OrderDetail AS ord
    INNER JOIN Proline.dbo.Exp_PackingList_InvoiceDetail AS inv
        ON ord.InvoiceNo = inv.InvoiceNo
    WHERE inv.shpStatus <> 'Delivered'
      AND inv.Distributor = ?
    GROUP BY inv.Distributor, ord.NAVCode, ord.Style, ord.Colour, ord.OrdSize
),
Stock AS (
    SELECT
        s.Distributor,
        s.Brand,
        Style,
        Colour,
        SSize,
        s.SKU,
        s.CurrentStockDate AS dtStock,
        LatestStock,
        CommittedQty AS LatestCmtQty,
        Country AS Region,
        ColourStatus,
        dtColLaunch,
        SKUOldMonths,
        StockMonths,
        InTransitMonths,
        OpenOrders,
        CartonQty,
        shpQty,
        Disappear_NewOrder,
        AllocQty
    FROM khPriority.dbo.vw_Active_SKU_byDistributors s
    INNER JOIN dbMerchandising.dbo.tblSKUByDistributor d
        ON s.SKU COLLATE SQL_Latin1_General_CP1_CI_AS = d.SKU COLLATE SQL_Latin1_General_CP1_CI_AS
       AND s.Distributor COLLATE SQL_Latin1_General_CP1_CI_AS = d.Distributor COLLATE SQL_Latin1_General_CP1_CI_AS
    WHERE s.Distributor = ?
),
Scorecard AS (
    SELECT
        ? AS SelectedAnchor,
        DATEADD(YEAR, -1, ?) AS SalesAnchorStart,
        DATEADD(DAY, -1, ?) AS SalesAnchorEnd,
        st.Distributor,
        st.Brand,
        st.Style,
        st.Colour,
        st.SSize,
        st.SKU,
        st.dtStock,
        st.Region,
        st.ColourStatus,
        st.dtColLaunch,
        st.SKUOldMonths,
        st.StockMonths,
        st.InTransitMonths,
        st.CartonQty,
        st.Disappear_NewOrder,
        st.shpQty,
        st.AllocQty,
        ISNULL(st.LatestStock,0) AS StockQty,
        ISNULL(st.LatestCmtQty,0) AS PipelineQty,
        ISNULL(st.LatestStock,0) + ISNULL(st.LatestCmtQty,0) AS AvailableQty,
        ISNULL(it.Ship_Qty,0) AS InTransitQty,
        ISNULL(st.OpenOrders,0) AS OpenOrders,
        ISNULL(i.MonthsUsed,0) AS MonthsUsed,
        ISNULL(i.Sales6M,0) AS Sales6M,
        ISNULL(i.AvgMonthlySales6M,0) AS AvgMonthlySales6M,
        ISNULL(TRY_CAST(st.StockMonths AS INT), 0) + ISNULL(TRY_CAST(st.InTransitMonths AS INT), 0) AS StockReqMonths,
        CAST(
            ISNULL(i.AvgMonthlySales6M,0) *
            CASE
                WHEN (ISNULL(TRY_CAST(st.StockMonths AS INT),0) + ISNULL(TRY_CAST(st.InTransitMonths AS INT),0)) > 0
                    THEN (ISNULL(TRY_CAST(st.StockMonths AS INT),0) + ISNULL(TRY_CAST(st.InTransitMonths AS INT),0))
                ELSE 6
            END
            AS DECIMAL(18,2)
        ) AS ReqStock,
        FLOOR(
          CASE
            WHEN ISNULL(st.CartonQty, 0) = 0 THEN 0
            ELSE
              CAST(
                (ISNULL(st.LatestStock,0) + ISNULL(it.Ship_Qty,0)) -
                (ISNULL(i.AvgMonthlySales6M,0) *
                 CASE
                    WHEN (ISNULL(TRY_CAST(st.StockMonths AS INT),0) + ISNULL(TRY_CAST(st.InTransitMonths AS INT),0)) > 0
                        THEN (ISNULL(TRY_CAST(st.StockMonths AS INT),0) + ISNULL(TRY_CAST(st.InTransitMonths AS INT),0))
                    ELSE 6
                 END)
                AS DECIMAL(18,2)
              ) / NULLIF(st.CartonQty, 0)
          END
        ) * CartonQty AS GapToReqStock,
        CAST(
            CASE
                WHEN (ISNULL(i.AvgMonthlySales6M,0) *
                      CASE
                        WHEN ISNULL(TRY_CAST(st.StockMonths AS INT),0) > 0
                            THEN ISNULL(TRY_CAST(st.StockMonths AS INT),0)
                        ELSE 6
                      END) <= 0 THEN 0
                ELSE ((ISNULL(st.LatestStock,0) + ISNULL(st.LatestCmtQty,0)) * 100.0 /
                      (i.AvgMonthlySales6M *
                       CASE
                        WHEN ISNULL(TRY_CAST(st.StockMonths AS INT),0) > 0
                            THEN ISNULL(TRY_CAST(st.StockMonths AS INT),0)
                        ELSE 6
                       END))
            END
            AS DECIMAL(18,2)
        ) AS CoveragePct,
        CAST(
            CASE
                WHEN ISNULL(i.AvgMonthlySales6M,0) <= 0 THEN 0
                ELSE (ISNULL(st.LatestStock,0) + ISNULL(st.LatestCmtQty,0)) * 1.0 / i.AvgMonthlySales6M
            END AS DECIMAL(18,2)
        ) AS CoverageMonths,
        CAST(
            CASE
                WHEN (ISNULL(i.AvgMonthlySales6M,0) *
                      CASE
                        WHEN (ISNULL(TRY_CAST(st.StockMonths AS INT),0) + ISNULL(TRY_CAST(st.InTransitMonths AS INT),0)) > 0
                            THEN (ISNULL(TRY_CAST(st.StockMonths AS INT),0) + ISNULL(TRY_CAST(st.InTransitMonths AS INT),0))
                        ELSE 6
                      END) <= 0 THEN 0
                ELSE ((ISNULL(st.LatestStock,0) + ISNULL(st.LatestCmtQty,0) + ISNULL(it.Ship_Qty,0)) * 100.0 /
                      (i.AvgMonthlySales6M *
                       CASE
                        WHEN (ISNULL(TRY_CAST(st.StockMonths AS INT),0) + ISNULL(TRY_CAST(st.InTransitMonths AS INT),0)) > 0
                            THEN (ISNULL(TRY_CAST(st.StockMonths AS INT),0) + ISNULL(TRY_CAST(st.InTransitMonths AS INT),0))
                        ELSE 6
                       END))
            END
            AS DECIMAL(18,2)
        ) AS CoveragePct_InclInTransit,
        (CASE WHEN st.Disappear_NewOrder = 1 THEN '0' ELSE
            FLOOR(
              CASE
                WHEN ISNULL(st.CartonQty, 0) = 0 THEN 0
                ELSE
                  CAST(
                      (ISNULL(st.LatestStock,0) + ISNULL(it.Ship_Qty,0) + ISNULL(st.OpenOrders,0) + ISNULL(st.shpQty,0) + ISNULL(st.AllocQty,0))
                    - (ISNULL(i.AvgMonthlySales6M,0) *
                        CASE
                          WHEN (ISNULL(TRY_CAST(st.StockMonths AS INT),0) + ISNULL(TRY_CAST(st.InTransitMonths AS INT),0)) > 0
                            THEN (ISNULL(TRY_CAST(st.StockMonths AS INT),0) + ISNULL(TRY_CAST(st.InTransitMonths AS INT),0))
                          ELSE 6
                        END
                      )
                    AS DECIMAL(18,2)
                  )
                  / NULLIF(st.CartonQty, 0)
              END
            )
         END) * CartonQty AS ReqNewOrderQty
    FROM Stock st
    LEFT JOIN SalesAvg i
        ON st.Distributor COLLATE SQL_Latin1_General_CP1_CI_AS = i.Distributor COLLATE SQL_Latin1_General_CP1_CI_AS
       AND st.SKU COLLATE SQL_Latin1_General_CP1_CI_AS = i.SKU COLLATE SQL_Latin1_General_CP1_CI_AS
    LEFT JOIN inTransit it
      ON st.Distributor COLLATE SQL_Latin1_General_CP1_CI_AS = it.Distributor COLLATE SQL_Latin1_General_CP1_CI_AS
     AND st.SKU COLLATE SQL_Latin1_General_CP1_CI_AS = it.NAVCode COLLATE SQL_Latin1_General_CP1_CI_AS
)
SELECT *
FROM Scorecard
ORDER BY Distributor, Brand, Style, Colour, SSize;
"""


BRAND_INVENTORY_TREND_QUERY = """
WITH MonthList AS (
    SELECT TOP 6
        DATEFROMPARTS(YEAR(s.CurrentStockDate), MONTH(s.CurrentStockDate), 1) AS MonthStart
    FROM khPriority.dbo.vw_Active_SKU_byDistributors s
    WHERE s.Distributor = ?
      AND s.CurrentStockDate <= ?
      AND s.CurrentStockDate IS NOT NULL
    GROUP BY DATEFROMPARTS(YEAR(s.CurrentStockDate), MONTH(s.CurrentStockDate), 1)
    ORDER BY MonthStart DESC
),
BrandMonth AS (
    SELECT
        ml.MonthStart,
        s.Brand,
        SUM(ISNULL(s.LatestStock, 0)) AS StockQty,
        SUM(ISNULL(s.LatestStock, 0) + ISNULL(s.CommittedQty, 0)) AS AvailableQty,
        COUNT(DISTINCT s.SKU) AS SKUCount
    FROM MonthList ml
    INNER JOIN khPriority.dbo.vw_Active_SKU_byDistributors s
        ON DATEFROMPARTS(YEAR(s.CurrentStockDate), MONTH(s.CurrentStockDate), 1) = ml.MonthStart
       AND s.Distributor = ?
       AND s.CurrentStockDate >= DATEADD(MONTH, -7, ?)
       AND s.CurrentStockDate <= ?
    GROUP BY ml.MonthStart, s.Brand
)
SELECT
    MonthStart,
    Brand,
    StockQty,
    AvailableQty,
    SKUCount
FROM BrandMonth
ORDER BY MonthStart ASC, Brand ASC;
"""


def get_scorecard_data(anchor_date=None):
    if anchor_date is None:
        anchor_date = get_default_anchor_date()

    cache_key = str(anchor_date)
    cached = _scorecard_cache.get(cache_key)
    if cached and (time() - cached["ts"]) < SCORECARD_CACHE_TTL_SECONDS:
        return cached["rows"]

    params = [
        anchor_date, anchor_date, CITADEL_DISTRIBUTOR,
        anchor_date, anchor_date,
        CITADEL_DISTRIBUTOR,
        CITADEL_DISTRIBUTOR,
        anchor_date, anchor_date, anchor_date
    ]

    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute(SCORECARD_QUERY, params)

    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()

    result = [dict(zip(columns, row)) for row in rows]
    _scorecard_cache[cache_key] = {"ts": time(), "rows": result}
    return result


def get_citadel_scorecard_data(anchor_date=None):
    return get_scorecard_data(anchor_date)


def get_brand_inventory_trend(
    anchor_date=None,
    scorecard_rows=None,
    max_brands=8,
    cache_suffix="",
    use_snapshot_query=True,
):
    if anchor_date is None:
        anchor_date = get_default_anchor_date()

    cache_key = f"trend:v5:{anchor_date}:{max_brands}:{cache_suffix}"
    cached = _scorecard_cache.get(cache_key)
    if cached and (time() - cached["ts"]) < SCORECARD_CACHE_TTL_SECONDS:
        return cached["data"]

    rows = []

    if use_snapshot_query:
        params = [CITADEL_DISTRIBUTOR, anchor_date, CITADEL_DISTRIBUTOR, anchor_date, anchor_date]
        try:
            conn = get_master_connection()
            cursor = conn.cursor()
            cursor.execute(BRAND_INVENTORY_TREND_QUERY, params)

            columns = [c[0] for c in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            conn.close()
        except Exception:
            rows = []

    result = build_brand_inventory_trend(rows, max_brands=max_brands)
    if not result["series"] and scorecard_rows:
        result = build_estimated_inventory_trend(scorecard_rows, anchor_date, max_brands=max_brands)
    if scorecard_rows:
        result["coverage_trend"] = build_estimated_coverage_trend(
            scorecard_rows,
            anchor_date,
            max_brands=max_brands,
        )

    _scorecard_cache[cache_key] = {"ts": time(), "data": result}
    return result


def _month_start(value):
    return date(value.year, value.month, 1)


def _shift_month(value, offset):
    month_index = (value.year * 12) + value.month - 1 + offset
    year = month_index // 12
    month = (month_index % 12) + 1
    return date(year, month, 1)


def build_brand_inventory_trend(rows, max_brands=8):
    rows = rows or []
    months = sorted({r.get("MonthStart") for r in rows if r.get("MonthStart")})
    labels = [m.strftime("%b %Y") if hasattr(m, "strftime") else str(m) for m in months]

    latest_month = months[-1] if months else None
    latest_rows = [r for r in rows if r.get("MonthStart") == latest_month]
    top_brands = [
        r.get("Brand") or "Unknown"
        for r in sorted(latest_rows, key=lambda x: _num(x.get("AvailableQty")), reverse=True)[:max_brands]
    ]

    palette = ["#21d4fd", "#84cc16", "#f59e0b", "#f87171", "#a78bfa", "#22c55e", "#38bdf8", "#fb7185"]
    row_map = {
        (r.get("Brand") or "Unknown", r.get("MonthStart")): r
        for r in rows
    }

    series = []
    movers = []
    for index, brand in enumerate(top_brands):
        values = [round(_num(row_map.get((brand, month), {}).get("AvailableQty")), 0) for month in months]
        stock_values = [round(_num(row_map.get((brand, month), {}).get("StockQty")), 0) for month in months]
        first_value = values[0] if values else 0
        last_value = values[-1] if values else 0
        change = round(last_value - first_value, 0)
        change_pct = round((change / first_value) * 100, 1) if first_value else 0

        series.append({
            "brand": brand,
            "color": palette[index % len(palette)],
            "values": values,
            "stock_values": stock_values,
            "change": change,
            "change_pct": change_pct,
        })
        movers.append({
            "Brand": brand,
            "FirstAvailable": first_value,
            "LastAvailable": last_value,
            "Change": change,
            "ChangePct": change_pct,
        })

    movers.sort(key=lambda item: abs(item["Change"]), reverse=True)

    return {
        "labels": labels,
        "series": series,
        "movers": movers[:5],
        "month_count": len(labels),
        "source_note": "Actual stock snapshots by brand.",
        "is_estimated": False,
        "coverage_trend": {"labels": labels, "series": [], "movers": [], "month_count": len(labels)},
    }


def build_estimated_inventory_trend(rows, anchor_date=None, max_brands=8):
    rows = rows or []
    if anchor_date is None:
        anchor_date = get_default_anchor_date()

    start_month = _month_start(anchor_date)
    months = [_shift_month(start_month, offset) for offset in range(-5, 1)]
    labels = [m.strftime("%b %Y") for m in months]

    grouped = defaultdict(lambda: {"available": 0.0, "monthly_sales": 0.0})
    for row in rows:
        brand = row.get("Brand") or "Unknown"
        grouped[brand]["available"] += _num(row.get("AvailableQty"))
        grouped[brand]["monthly_sales"] += _num(row.get("AvgMonthlySales6M"))

    top_brands = sorted(
        grouped.items(),
        key=lambda item: item[1]["available"],
        reverse=True,
    )[:max_brands]

    palette = ["#21d4fd", "#84cc16", "#f59e0b", "#f87171", "#a78bfa", "#22c55e", "#38bdf8", "#fb7185"]
    series = []
    movers = []

    for index, (brand, metrics) in enumerate(top_brands):
        current_available = metrics["available"]
        monthly_sales = metrics["monthly_sales"]
        values = [
            round(max(0.0, current_available + (monthly_sales * months_back)), 0)
            for months_back in range(5, -1, -1)
        ]
        first_value = values[0] if values else 0
        last_value = values[-1] if values else 0
        change = round(last_value - first_value, 0)
        change_pct = round((change / first_value) * 100, 1) if first_value else 0

        series.append({
            "brand": brand,
            "color": palette[index % len(palette)],
            "values": values,
            "stock_values": values,
            "change": change,
            "change_pct": change_pct,
        })
        movers.append({
            "Brand": brand,
            "FirstAvailable": first_value,
            "LastAvailable": last_value,
            "Change": change,
            "ChangePct": change_pct,
        })

    movers.sort(key=lambda item: abs(item["Change"]), reverse=True)

    return {
        "labels": labels,
        "series": series,
        "movers": movers[:5],
        "month_count": len(labels),
        "source_note": "Estimated from current available inventory and average monthly demand because historical stock snapshots were not available.",
        "is_estimated": True,
        "coverage_trend": {"labels": labels, "series": [], "movers": [], "month_count": len(labels)},
    }


def build_estimated_coverage_trend(rows, anchor_date=None, max_brands=8):
    rows = rows or []
    if anchor_date is None:
        anchor_date = get_default_anchor_date()

    start_month = _month_start(anchor_date)
    months = [_shift_month(start_month, offset) for offset in range(-5, 1)]
    labels = [m.strftime("%b %Y") for m in months]

    grouped = defaultdict(list)
    for row in rows:
        brand = row.get("Brand") or "Unknown"
        grouped[brand].append(row)

    top_brands = sorted(
        grouped.items(),
        key=lambda item: sum(_num(row.get("AvailableQty")) for row in item[1]),
        reverse=True,
    )[:max_brands]

    palette = ["#21d4fd", "#84cc16", "#f59e0b", "#f87171", "#a78bfa", "#22c55e", "#38bdf8", "#fb7185"]
    series = []
    movers = []

    for index, (brand, brand_rows) in enumerate(top_brands):
        values = []

        for months_back in range(5, -1, -1):
            weighted_available = 0.0
            weighted_required = 0.0

            for row in brand_rows:
                required = _num(row.get("ReqStock"))
                if required <= 0:
                    continue

                estimated_available = max(
                    0.0,
                    _num(row.get("AvailableQty")) + (_num(row.get("AvgMonthlySales6M")) * months_back),
                )
                weighted_available += min(estimated_available, required)
                weighted_required += required

            coverage = round((weighted_available * 100.0 / weighted_required), 1) if weighted_required else 0
            values.append(coverage)

        first_value = values[0] if values else 0
        last_value = values[-1] if values else 0
        change = round(last_value - first_value, 1)

        series.append({
            "brand": brand,
            "color": palette[index % len(palette)],
            "values": values,
            "change": change,
        })
        movers.append({
            "Brand": brand,
            "FirstCoverage": first_value,
            "LastCoverage": last_value,
            "Change": change,
        })

    movers.sort(key=lambda item: abs(item["Change"]), reverse=True)

    return {
        "labels": labels,
        "series": series,
        "movers": movers[:5],
        "month_count": len(labels),
        "source_note": "Avg coverage trend is SKU-weighted and capped at each SKU requirement, matching the current scorecard coverage view.",
        "is_estimated": True,
    }


def build_brand_summary(rows):
    grouped = defaultdict(list)

    for row in rows:
        brand = str(row.get("Brand") or "Unknown")
        grouped[brand].append(row)

    summary = []

    for brand, items in grouped.items():
        row_count = len(items)
        mature_items = [r for r in items if not _is_new_sku(r)]
        new_sku_count = row_count - len(mature_items)
        critical_count = sum(1 for r in mature_items if float(r.get("CoveragePct", 0) or 0) <= 20)
        low_cover_count = sum(1 for r in items if float(r.get("CoveragePct", 0) or 0) < 100)
        out_of_stock_count = sum(1 for r in mature_items if float(r.get("AvailableQty", 0) or 0) <= 0)
        req_order_count = sum(1 for r in items if float(r.get("ReqNewOrderQty", 0) or 0) > 0)

        avg_coverage = round(
            sum(min(100.0, float(r.get("CoveragePct", 0) or 0)) for r in items) / row_count, 2
        ) if row_count else 0

        avg_coverage_incl_intransit = round(
            sum(min(100.0, float(r.get("CoveragePct_InclInTransit", 0) or 0)) for r in items) / row_count, 2
        ) if row_count else 0

        total_available = round(sum(float(r.get("AvailableQty", 0) or 0) for r in items), 2)
        total_in_transit = round(sum(float(r.get("InTransitQty", 0) or 0) for r in items), 2)
        total_req_order = round(sum(float(r.get("ReqNewOrderQty", 0) or 0) for r in items), 2)

        summary.append({
            "Brand": brand,
            "Rows": row_count,
            "AvgCoveragePct": avg_coverage,
            "AvgCoveragePctInclInTransit": avg_coverage_incl_intransit,
            "CriticalCount": critical_count,
            "LowCoverageCount": low_cover_count,
            "OutOfStockCount": out_of_stock_count,
            "NewSKUCount": new_sku_count,
            "ReqOrderCount": req_order_count,
            "TotalAvailableQty": total_available,
            "TotalInTransitQty": total_in_transit,
            "TotalReqOrderQty": total_req_order
        })

    summary.sort(key=lambda x: (x["CriticalCount"], x["ReqOrderCount"], -x["AvgCoveragePct"]), reverse=True)
    return summary


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_new_sku(row):
    return _num(row.get("SKUOldMonths")) < 10


def _launch_year(row):
    launch = row.get("dtColLaunch")
    if hasattr(launch, "year"):
        return str(launch.year)
    if launch:
        launch_text = str(launch)
        return launch_text[:4] if len(launch_text) >= 4 else "Unknown"
    return "Unknown"


def _recalculate_requirement_row(row, requirement_months):
    months = _num(requirement_months)
    avg_sales = _num(row.get("AvgMonthlySales6M"))
    stock = _num(row.get("StockQty"))
    available = _num(row.get("AvailableQty"))
    in_transit = _num(row.get("InTransitQty"))
    open_orders = _num(row.get("OpenOrders"))
    shipped_qty = _num(row.get("shpQty"))
    alloc_qty = _num(row.get("AllocQty"))
    carton_qty = _num(row.get("CartonQty"))
    disappear_new_order = int(_num(row.get("Disappear_NewOrder")))

    req_stock = round(avg_sales * months, 2)
    row["StockReqMonths"] = months
    row["ReqStock"] = req_stock
    row["CoveragePct"] = round((available * 100.0 / req_stock), 2) if req_stock > 0 else 0
    row["CoveragePct_InclInTransit"] = round(((available + in_transit) * 100.0 / req_stock), 2) if req_stock > 0 else 0
    row["CoverageMonths"] = round(available / avg_sales, 2) if avg_sales > 0 else 0

    if carton_qty > 0:
        gap = ((stock + in_transit) - req_stock) / carton_qty
        row["GapToReqStock"] = int(gap // 1) * carton_qty

        order_gap = ((stock + in_transit + open_orders + shipped_qty + alloc_qty) - req_stock) / carton_qty
        req_order = int(order_gap // 1) * carton_qty
        row["ReqNewOrderQty"] = 0 if disappear_new_order == 1 or req_order >= 0 else abs(req_order)
    else:
        row["GapToReqStock"] = 0
        row["ReqNewOrderQty"] = 0


def apply_requirement_settings(rows, distributor=CITADEL_DISTRIBUTOR):
    copied_rows = [dict(row) for row in (rows or [])]
    settings = {
        _setting_key(item.get("Distributor"), item.get("Brand")): _num(item.get("RequirementMonths"))
        for item in get_requirement_settings(distributor)
    }

    if not settings:
        return copied_rows

    for row in copied_rows:
        key = _setting_key(row.get("Distributor"), row.get("Brand"))
        months = settings.get(key)
        if months and months > 0:
            _recalculate_requirement_row(row, months)

    return copied_rows


def apply_requirement_months(rows, requirement_months=None):
    copied_rows = [dict(row) for row in (rows or [])]
    if requirement_months in (None, ""):
        return copied_rows

    months = _num(requirement_months)
    if months <= 0:
        return copied_rows

    for row in copied_rows:
        _recalculate_requirement_row(row, months)

    return copied_rows


def build_scorecard_analysis(rows, brand_summary):
    rows = rows or []
    brand_summary = brand_summary or []
    total_rows = len(rows)
    mature_rows = [r for r in rows if not _is_new_sku(r)]
    new_sku_rows = [r for r in rows if _is_new_sku(r)]

    critical_skus = sum(1 for r in mature_rows if _num(r.get("CoveragePct")) <= 20)
    low_coverage_skus = sum(1 for r in rows if _num(r.get("CoveragePct")) < 100)
    out_of_stock_skus = sum(1 for r in mature_rows if _num(r.get("AvailableQty")) <= 0)
    reorder_skus = sum(1 for r in rows if _num(r.get("ReqNewOrderQty")) > 0)
    healthy_skus = max(total_rows - low_coverage_skus, 0)
    new_skus = len(new_sku_rows)

    avg_coverage = round(sum(min(100.0, _num(r.get("CoveragePct"))) for r in rows) / total_rows, 1) if total_rows else 0
    avg_coverage_it = round(sum(min(100.0, _num(r.get("CoveragePct_InclInTransit"))) for r in rows) / total_rows, 1) if total_rows else 0
    total_available = round(sum(_num(r.get("AvailableQty")) for r in rows), 0)
    total_stock = round(sum(_num(r.get("StockQty")) for r in rows), 0)
    total_pipeline = round(sum(_num(r.get("PipelineQty")) for r in rows), 0)
    total_in_transit = round(sum(_num(r.get("InTransitQty")) for r in rows), 0)
    total_req_order = round(sum(max(0, _num(r.get("ReqNewOrderQty"))) for r in rows), 0)
    total_sales_6m = round(sum(_num(r.get("Sales6M")) for r in rows), 0)

    health_score = round(((healthy_skus + ((low_coverage_skus - critical_skus) * 0.45)) / total_rows) * 100, 1) if total_rows else 0

    top_brand_risks = sorted(
        brand_summary,
        key=lambda b: (b.get("CriticalCount", 0), b.get("OutOfStockCount", 0), b.get("TotalReqOrderQty", 0), -b.get("AvgCoveragePct", 0)),
        reverse=True,
    )[:5]

    urgent_skus = sorted(
        mature_rows,
        key=lambda r: (
            0 if _num(r.get("AvailableQty")) <= 0 or _num(r.get("CoveragePct")) <= 20 else 1,
            _num(r.get("CoveragePct")),
            -_num(r.get("AvgMonthlySales6M")),
        ),
    )[:8]

    new_skus_by_year = []
    new_year_groups = defaultdict(list)
    for row in new_sku_rows:
        new_year_groups[_launch_year(row)].append(row)

    for year, items in new_year_groups.items():
        new_skus_by_year.append({
            "Year": year,
            "Count": len(items),
            "Available": round(sum(_num(r.get("AvailableQty")) for r in items), 0),
            "Sales6M": round(sum(_num(r.get("Sales6M")) for r in items), 0),
        })

    new_skus_by_year.sort(key=lambda item: item["Year"], reverse=True)

    def sku_detail(row):
        return {
            "Brand": row.get("Brand") or "-",
            "SKU": row.get("SKU") or "-",
            "Style": row.get("Style") or "-",
            "Colour": row.get("Colour") or "-",
            "Size": row.get("SSize") or "-",
            "Available": round(_num(row.get("AvailableQty")), 0),
            "InTransit": round(_num(row.get("InTransitQty")), 0),
            "ReqOrder": round(max(0, _num(row.get("ReqNewOrderQty"))), 0),
            "Coverage": round(_num(row.get("CoveragePct")), 1),
            "Sales6M": round(_num(row.get("Sales6M")), 0),
            "SKUOldMonths": round(_num(row.get("SKUOldMonths")), 1),
            "LaunchYear": _launch_year(row),
        }

    def brand_detail(brand):
        return {
            "Brand": brand.get("Brand") or "-",
            "Rows": brand.get("Rows", 0),
            "AvgCoverage": round(_num(brand.get("AvgCoveragePct")), 1),
            "Available": round(_num(brand.get("TotalAvailableQty")), 0),
            "InTransit": round(_num(brand.get("TotalInTransitQty")), 0),
            "ReqOrder": round(_num(brand.get("TotalReqOrderQty")), 0),
            "Critical": brand.get("CriticalCount", 0),
        }

    kpi_details = {
        "available": {
            "title": "Available Inventory by Brand",
            "description": "All brands by available quantity in the current scorecard.",
            "type": "brand",
            "rows": [brand_detail(b) for b in sorted(brand_summary, key=lambda b: _num(b.get("TotalAvailableQty")), reverse=True)],
        },
        "in_transit": {
            "title": "In-Transit Inventory by Brand",
            "description": "All brands with open in-transit quantity.",
            "type": "brand",
            "rows": [brand_detail(b) for b in sorted(brand_summary, key=lambda b: _num(b.get("TotalInTransitQty")), reverse=True) if _num(b.get("TotalInTransitQty")) > 0],
        },
        "req_order": {
            "title": "Required Order Detail",
            "description": "SKU rows requiring replenishment, sorted by required order quantity.",
            "type": "sku",
            "rows": [sku_detail(r) for r in sorted(rows, key=lambda r: _num(r.get("ReqNewOrderQty")), reverse=True) if _num(r.get("ReqNewOrderQty")) > 0],
        },
        "critical": {
            "title": "Critical SKU Detail",
            "description": "Mature SKU rows at or below 20% coverage. SKUs under 10 months old are tracked separately as New SKU.",
            "type": "sku",
            "rows": [sku_detail(r) for r in sorted(mature_rows, key=lambda r: (_num(r.get("CoveragePct")), -_num(r.get("AvgMonthlySales6M")))) if _num(r.get("CoveragePct")) <= 20],
        },
        "below_target": {
            "title": "Below Target Coverage",
            "description": "SKU rows below 100% coverage, sorted by lowest coverage first.",
            "type": "sku",
            "rows": [sku_detail(r) for r in sorted(rows, key=lambda r: (_num(r.get("CoveragePct")), -_num(r.get("AvgMonthlySales6M")))) if _num(r.get("CoveragePct")) < 100],
        },
        "sales_6m": {
            "title": "Six-Month Sales by SKU",
            "description": "Highest selling SKU rows in the active six-month sales window.",
            "type": "sku",
            "rows": [sku_detail(r) for r in sorted(rows, key=lambda r: _num(r.get("Sales6M")), reverse=True)],
        },
        "new_sku": {
            "title": "New SKU Detail",
            "description": "SKU rows under 10 SKU old months, grouped by launch year.",
            "type": "sku",
            "rows": [sku_detail(r) for r in sorted(new_sku_rows, key=lambda r: (_launch_year(r), str(r.get("Brand") or ""), str(r.get("SKU") or "")), reverse=True)],
        },
    }

    recommendations = []
    if critical_skus or out_of_stock_skus:
        recommendations.append(f"Prioritize {critical_skus} critical SKU(s) and {out_of_stock_skus} out-of-stock SKU(s) before reviewing lower-risk replenishment.")
    if total_req_order > 0:
        recommendations.append(f"Required order quantity is {total_req_order:,.0f} units; validate carton rounding and open-order assumptions before release.")
    if avg_coverage_it > avg_coverage:
        recommendations.append(f"In-transit inventory lifts average coverage from {avg_coverage}% to {avg_coverage_it}%; confirm ETA before postponing buys.")
    if top_brand_risks:
        recommendations.append(f"Highest brand exposure is {top_brand_risks[0]['Brand']} with {top_brand_risks[0]['CriticalCount']} critical row(s).")
    if not recommendations:
        recommendations.append("Citadel inventory health is stable. Continue monitoring high-sales SKUs and coverage drift.")

    return {
        "summary": {
            "health_score": health_score,
            "total_rows": total_rows,
            "critical_skus": critical_skus,
            "low_coverage_skus": low_coverage_skus,
            "out_of_stock_skus": out_of_stock_skus,
            "new_skus": new_skus,
            "reorder_skus": reorder_skus,
            "healthy_skus": healthy_skus,
            "avg_coverage": avg_coverage,
            "avg_coverage_it": avg_coverage_it,
            "total_available": total_available,
            "total_stock": total_stock,
            "total_pipeline": total_pipeline,
            "total_in_transit": total_in_transit,
            "total_req_order": total_req_order,
            "total_sales_6m": total_sales_6m,
        },
        "top_brand_risks": top_brand_risks,
        "urgent_skus": urgent_skus,
        "new_skus_by_year": new_skus_by_year,
        "recommendations": recommendations,
        "kpi_details": kpi_details,
    }


def get_brand_detail(rows, brand_name):
    return [
        r for r in rows
        if str(r.get("Brand") or "").lower() == brand_name.lower()
    ]


def save_presentation_rows_to_db(rows, source_file):
    conn = get_master_connection()
    cursor = conn.cursor()

    batch_id = str(uuid.uuid4())

    for row in rows:
        cursor.execute("""
            INSERT INTO khPriority.dbo.InventoryPresentationData (
                upload_batch_id,
                source_file,
                Distributor,
                Brand,
                Style,
                Colour,
                SSize,
                SKU,
                StockQty,
                PipelineQty,
                AvailableQty,
                InTransitQty,
                AvgMonthlySales6M,
                StockReqMonths,
                ReqStock,
                CoveragePct,
                CoveragePctInclInTransit,
                CoverageMonths,
                ReqNewOrderQty,
                RiskStatus
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            batch_id,
            source_file,
            row.get("Distributor"),
            row.get("Brand"),
            row.get("Style"),
            row.get("Colour"),
            row.get("SSize"),
            row.get("SKU"),
            row.get("StockQty"),
            row.get("PipelineQty"),
            row.get("AvailableQty"),
            row.get("InTransitQty"),
            row.get("AvgMonthlySales6M"),
            row.get("StockReqMonths"),
            row.get("ReqStock"),
            row.get("CoveragePct"),
            row.get("CoveragePctInclInTransit"),
            row.get("CoverageMonths"),
            row.get("ReqNewOrderQty"),
            row.get("RiskStatus"),
        ))

    conn.commit()
    conn.close()

    return batch_id


def get_latest_presentation_batch():
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT TOP 1 upload_batch_id
        FROM khPriority.dbo.InventoryPresentationData
        ORDER BY uploaded_at DESC, id DESC
    """)

    row = cursor.fetchone()
    conn.close()

    return row[0] if row else None


def get_rows_from_named_table(table_name):
    """Query every row from any named table on the live server.

    table_name must be validated against get_available_inventory_tables()
    by the caller before arriving here — it is used directly as an SQL identifier.
    """
    conn = get_master_connection()
    cursor = conn.cursor()
    safe = table_name.replace("]", "").replace("[", "")
    cursor.execute(f"SELECT * FROM khPriority.dbo.[{safe}]")
    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    return [dict(zip(columns, row)) for row in rows]


def get_presentation_rows_from_db(batch_id=None):
    if not batch_id:
        batch_id = get_latest_presentation_batch()

    if not batch_id:
        return []

    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            Distributor,
            Brand,
            Style,
            Colour,
            SSize,
            SKU,
            StockQty,
            PipelineQty,
            AvailableQty,
            InTransitQty,
            AvgMonthlySales6M,
            StockReqMonths,
            ReqStock,
            CoveragePct,
            CoveragePctInclInTransit,
            CoverageMonths,
            ReqNewOrderQty,
            RiskStatus,
            source_file,
            uploaded_at
        FROM khPriority.dbo.InventoryPresentationData
        WHERE upload_batch_id = ?
        ORDER BY Brand, Style, Colour, SSize
    """, batch_id)

    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()

    return [dict(zip(columns, row)) for row in rows]


def get_presentation_batches():
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            upload_batch_id,
            MAX(source_file) AS source_file,
            MAX(uploaded_at) AS uploaded_at,
            COUNT(*) AS row_count
        FROM khPriority.dbo.InventoryPresentationData
        GROUP BY upload_batch_id
        ORDER BY MAX(uploaded_at) DESC
    """)

    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()

    return [dict(zip(columns, row)) for row in rows]


def delete_presentation_batch(batch_id):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM khPriority.dbo.InventoryPresentationData
        WHERE upload_batch_id = ?
    """, batch_id)

    conn.commit()
    conn.close()


def build_saved_inventory_brand_tree(rows):
    brand_map = defaultdict(list)

    for row in rows:
        brand = str(row.get("Brand") or "Unknown")
        brand_map[brand].append(row)

    result = []

    for brand, brand_rows in brand_map.items():
        style_map = defaultdict(list)

        for row in brand_rows:
            style = str(row.get("Style") or "Unknown")
            style_map[style].append(row)

        style_nodes = []
        for style, style_rows in style_map.items():
            style_nodes.append({
                "style": style,
                "row_count": len(style_rows),
                "critical_count": sum(1 for r in style_rows if str(r.get("RiskStatus")) == "Critical"),
                "out_of_stock_count": sum(1 for r in style_rows if str(r.get("RiskStatus")) == "Out of Stock"),
                "new_order_count": sum(1 for r in style_rows if float(r.get("ReqNewOrderQty", 0) or 0) > 0),
                "avg_coverage": round(
                    sum(min(100.0, float(r.get("CoveragePct", 0) or 0)) for r in style_rows) / len(style_rows), 2
                ) if style_rows else 0,
                "avg_coverage_incl_intransit": round(
                    sum(min(100.0, float(r.get("CoveragePctInclInTransit", 0) or 0)) for r in style_rows) / len(style_rows), 2
                ) if style_rows else 0,
                "rows": style_rows
            })

        style_nodes.sort(key=lambda x: (x["critical_count"], x["new_order_count"], -x["avg_coverage"]), reverse=True)

        result.append({
            "brand": brand,
            "row_count": len(brand_rows),
            "critical_count": sum(1 for r in brand_rows if str(r.get("RiskStatus")) == "Critical"),
            "out_of_stock_count": sum(1 for r in brand_rows if str(r.get("RiskStatus")) == "Out of Stock"),
            "new_order_count": sum(1 for r in brand_rows if float(r.get("ReqNewOrderQty", 0) or 0) > 0),
            "avg_coverage": round(
                sum(min(100.0, float(r.get("CoveragePct", 0) or 0)) for r in brand_rows) / len(brand_rows), 2
            ) if brand_rows else 0,
            "avg_coverage_incl_intransit": round(
                sum(min(100.0, float(r.get("CoveragePctInclInTransit", 0) or 0)) for r in brand_rows) / len(brand_rows), 2
            ) if brand_rows else 0,
            "styles": style_nodes
        })

    result.sort(key=lambda x: (x["critical_count"], x["new_order_count"], -x["avg_coverage"]), reverse=True)
    return result

def get_presentation_rows_by_batch(batch_id):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            Distributor,
            Brand,
            Style,
            Colour,
            SSize,
            SKU,
            StockQty,
            PipelineQty,
            AvailableQty,
            InTransitQty,
            AvgMonthlySales6M,
            StockReqMonths,
            ReqStock,
            CoveragePct,
            CoveragePctInclInTransit,
            CoverageMonths,
            ReqNewOrderQty,
            RiskStatus,
            source_file,
            uploaded_at
        FROM khPriority.dbo.InventoryPresentationData
        WHERE upload_batch_id = ?
    """, batch_id)

    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()

    return [dict(zip(columns, row)) for row in rows]


def compare_presentation_batches(old_batch_id, new_batch_id):
    old_rows = get_presentation_rows_by_batch(old_batch_id)
    new_rows = get_presentation_rows_by_batch(new_batch_id)

    old_map = {str(r.get("SKU")): r for r in old_rows}
    new_map = {str(r.get("SKU")): r for r in new_rows}

    all_skus = sorted(set(old_map.keys()) | set(new_map.keys()))
    comparisons = []

    for sku in all_skus:
        old = old_map.get(sku, {})
        new = new_map.get(sku, {})

        old_stock = float(old.get("StockQty", 0) or 0)
        new_stock = float(new.get("StockQty", 0) or 0)

        old_available = float(old.get("AvailableQty", 0) or 0)
        new_available = float(new.get("AvailableQty", 0) or 0)

        old_cov = float(old.get("CoveragePct", 0) or 0)
        new_cov = float(new.get("CoveragePct", 0) or 0)

        old_req = float(old.get("ReqNewOrderQty", 0) or 0)
        new_req = float(new.get("ReqNewOrderQty", 0) or 0)

        comparisons.append({
            "Distributor": new.get("Distributor") or old.get("Distributor"),
            "Brand": new.get("Brand") or old.get("Brand"),
            "Style": new.get("Style") or old.get("Style"),
            "Colour": new.get("Colour") or old.get("Colour"),
            "SSize": new.get("SSize") or old.get("SSize"),
            "SKU": sku,
            "OldStockQty": round(old_stock, 2),
            "NewStockQty": round(new_stock, 2),
            "StockChange": round(new_stock - old_stock, 2),
            "OldAvailableQty": round(old_available, 2),
            "NewAvailableQty": round(new_available, 2),
            "AvailableChange": round(new_available - old_available, 2),
            "OldCoveragePct": round(old_cov, 2),
            "NewCoveragePct": round(new_cov, 2),
            "CoverageChange": round(new_cov - old_cov, 2),
            "OldReqNewOrderQty": round(old_req, 2),
            "NewReqNewOrderQty": round(new_req, 2),
            "ReqOrderChange": round(new_req - old_req, 2),
            "OldRiskStatus": old.get("RiskStatus"),
            "NewRiskStatus": new.get("RiskStatus"),
        })

    return comparisons

def get_top_50_high_sales_inventory(batch_id=None):
    rows = get_presentation_rows_from_db(batch_id)

    rows = sorted(
        rows,
        key=lambda r: (
            float(r.get("AvgMonthlySales6M", 0) or 0),
            -float(r.get("CoveragePct", 0) or 0),
            float(r.get("ReqNewOrderQty", 0) or 0)
        ),
        reverse=True
    )

    return rows[:50]


def get_top_high_sales_risky_inventory(batch_id=None, limit=50):
    rows = get_presentation_rows_from_db(batch_id)

    rows = sorted(
        rows,
        key=lambda r: float(r.get("AvgMonthlySales6M", 0) or 0),
        reverse=True
    )

    rows = rows[:200]

    risky_rows = []
    for r in rows:
        coverage = float(r.get("CoveragePct", 0) or 0)
        req = float(r.get("ReqNewOrderQty", 0) or 0)
        risk = str(r.get("RiskStatus") or "")

        if (
            coverage <= 60 or
            req > 0 or
            risk in ["Critical", "High Risk", "Out of Stock"]
        ):
            risky_rows.append(r)

    return risky_rows[:limit]


def _inventory_rows(sql, params=None):
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params or [])
    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    return [dict(zip(columns, row)) for row in rows]


def _inventory_scalar(sql, params=None):
    rows = _inventory_rows(sql, params)
    if not rows:
        return None
    return next(iter(rows[0].values()))


def _org_clause(org_id, alias="i"):
    if org_id:
        return f" AND {alias}.org_id = ?"
    return ""


def _dashboard_filters_clause(filters, params):
    clause = ""
    if filters.get("brand"):
        clause += " AND c.brand = ?"
        params.append(filters["brand"])
    if filters.get("category"):
        clause += " AND c.category = ?"
        params.append(filters["category"])
    if filters.get("status"):
        clause += " AND i.stock_status = ?"
        params.append(filters["status"])
    if filters.get("warehouse"):
        clause += " AND i.warehouse_code = ?"
        params.append(filters["warehouse"])
    return clause


def _latest_inventory_snapshot(org_id=None):
    params = []
    clause = _org_clause(org_id, "i")
    if org_id:
        params.append(org_id)
    return _inventory_scalar(
        f"SELECT MAX(i.snapshot_date) AS snapshot_date FROM khPriority.dbo.Inventory_TestData i WHERE 1=1{clause}",
        params,
    )


def get_inventory_dashboard_filter_options(org_id=None):
    params = []
    clause_i = _org_clause(org_id, "i")
    if org_id:
        params.append(org_id)

    brands = _inventory_rows(
        f"""
        SELECT DISTINCT c.brand AS value
        FROM khPriority.dbo.Catalog_TestData c
        INNER JOIN khPriority.dbo.Inventory_TestData i
            ON i.sku = c.sku AND i.org_id = c.org_id
        WHERE c.is_active = 1{clause_i}
        ORDER BY c.brand
        """,
        params,
    )
    categories = _inventory_rows(
        f"""
        SELECT DISTINCT c.category AS value
        FROM khPriority.dbo.Catalog_TestData c
        INNER JOIN khPriority.dbo.Inventory_TestData i
            ON i.sku = c.sku AND i.org_id = c.org_id
        WHERE c.is_active = 1{clause_i}
        ORDER BY c.category
        """,
        params,
    )
    statuses = _inventory_rows(
        f"""
        SELECT DISTINCT i.stock_status AS value
        FROM khPriority.dbo.Inventory_TestData i
        WHERE 1=1{clause_i}
        ORDER BY i.stock_status
        """,
        params,
    )
    warehouses = _inventory_rows(
        f"""
        SELECT DISTINCT i.warehouse_code AS code, i.warehouse_name AS name
        FROM khPriority.dbo.Inventory_TestData i
        WHERE 1=1{clause_i}
        ORDER BY i.warehouse_name
        """,
        params,
    )

    return {
        "brands": [r["value"] for r in brands],
        "categories": [r["value"] for r in categories],
        "statuses": [r["value"] for r in statuses],
        "warehouses": warehouses,
    }


def _latest_inventory_rows(org_id=None, snapshot_date=None, filters=None):
    filters = filters or {}
    snapshot_date = snapshot_date or _latest_inventory_snapshot(org_id)
    if not snapshot_date:
        return [], None

    params = [snapshot_date]
    org_filter = _org_clause(org_id, "i")
    if org_id:
        params.append(org_id)
    extra_filter = _dashboard_filters_clause(filters, params)

    rows = _inventory_rows(
        f"""
        SELECT
            i.org_id,
            i.snapshot_date,
            i.warehouse_code,
            i.warehouse_name,
            i.style_code,
            i.sku,
            i.on_hand_qty,
            i.reserved_qty,
            i.available_qty,
            i.in_transit_qty,
            i.reorder_point,
            i.safety_stock_qty,
            i.unit_cost,
            i.inventory_value,
            i.stock_status,
            i.last_received_date,
            c.catalog_id,
            c.brand,
            c.product_name,
            c.category,
            c.color_name,
            c.size_range,
            c.season_name,
            c.list_price,
            c.cost_price,
            c.image_url,
            c.image_alt
        FROM khPriority.dbo.Inventory_TestData i
        INNER JOIN khPriority.dbo.Catalog_TestData c
            ON c.sku = i.sku AND c.org_id = i.org_id
        WHERE i.snapshot_date = ?{org_filter}{extra_filter}
        ORDER BY
            CASE i.stock_status
                WHEN 'Low Stock' THEN 1
                WHEN 'Reorder' THEN 2
                WHEN 'Overstock' THEN 3
                ELSE 4
            END,
            c.brand,
            c.product_name
        """,
        params,
    )
    return rows, snapshot_date


def _sales_by_style(org_id=None, snapshot_date=None, days=90):
    if not snapshot_date:
        return {}

    params = [snapshot_date, snapshot_date]
    org_filter = _org_clause(org_id, "s")
    if org_id:
        params.append(org_id)

    rows = _inventory_rows(
        f"""
        SELECT
            s.style_code,
            SUM(s.quantity) AS qty_sold,
            SUM(s.net_sales) AS net_sales,
            SUM(s.profit_amount) AS profit_amount,
            COUNT(DISTINCT s.order_no) AS order_count
        FROM khPriority.dbo.Sales_TestData s
        WHERE s.sale_date >= DATEADD(DAY, -{int(days) - 1}, ?)
          AND s.sale_date <= ?
          AND s.order_status <> 'Returned'{org_filter}
        GROUP BY s.style_code
        """,
        params,
    )
    return {str(row["style_code"]): row for row in rows}


def _risk_level(row, daily_sales):
    available = _num(row.get("available_qty"))
    safety = _num(row.get("safety_stock_qty"))
    reorder = _num(row.get("reorder_point"))
    reserved = _num(row.get("reserved_qty"))
    on_hand = max(_num(row.get("on_hand_qty")), 1)
    reserve_pressure = reserved / on_hand

    if available <= safety:
        return "Critical", 92
    if available <= reorder:
        return "Reorder", 76
    if daily_sales > 0 and available / daily_sales <= 14:
        return "Velocity Risk", 68
    if row.get("stock_status") == "Overstock":
        return "Overstock", 44
    if reserve_pressure >= 0.35:
        return "Reservation Pressure", 52
    return "Healthy", 18


def _enrich_inventory_rows(rows, sales_map):
    enriched = []
    for row in rows:
        sales = sales_map.get(str(row.get("style_code")), {})
        qty_90 = _num(sales.get("qty_sold"))
        daily_sales = qty_90 / 90 if qty_90 else 0
        days_cover = round(_num(row.get("available_qty")) / daily_sales, 1) if daily_sales else None
        risk_level, risk_score = _risk_level(row, daily_sales)
        margin_pct = (
            round((_num(sales.get("profit_amount")) / _num(sales.get("net_sales"))) * 100, 1)
            if _num(sales.get("net_sales")) else 0
        )
        enriched.append({
            **row,
            "sales_qty_90": round(qty_90, 0),
            "net_sales_90": round(_num(sales.get("net_sales")), 2),
            "profit_90": round(_num(sales.get("profit_amount")), 2),
            "margin_pct": margin_pct,
            "order_count_90": int(_num(sales.get("order_count"))),
            "daily_sales": round(daily_sales, 2),
            "days_cover": days_cover,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "reserve_pressure": round((_num(row.get("reserved_qty")) / max(_num(row.get("on_hand_qty")), 1)) * 100, 1),
            "gross_margin_unit": round(_num(row.get("list_price")) - _num(row.get("cost_price")), 2),
        })
    return enriched


def _group_summary(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[str(row.get(key) or "Unknown")].append(row)

    result = []
    for name, items in groups.items():
        available = sum(_num(r.get("available_qty")) for r in items)
        value = sum(_num(r.get("inventory_value")) for r in items)
        risk = sum(1 for r in items if r.get("risk_level") in ("Critical", "Reorder", "Velocity Risk"))
        result.append({
            "name": name,
            "count": len(items),
            "available": round(available, 0),
            "inventory_value": round(value, 2),
            "risk_count": risk,
            "avg_days_cover": round(
                sum(_num(r.get("days_cover")) for r in items if r.get("days_cover") is not None) /
                max(sum(1 for r in items if r.get("days_cover") is not None), 1),
                1,
            ),
            "sales_qty_90": round(sum(_num(r.get("sales_qty_90")) for r in items), 0),
        })

    return sorted(result, key=lambda item: (item["risk_count"], item["sales_qty_90"]), reverse=True)


def _inventory_trend(org_id=None, months=24):
    latest_snapshot = _latest_inventory_snapshot(org_id)
    if not latest_snapshot:
        return {"labels": [], "available": [], "value": [], "risk": [], "points": []}

    params = [latest_snapshot, latest_snapshot]
    org_filter = _org_clause(org_id, "i")
    if org_id:
        params.append(org_id)

    rows = _inventory_rows(
        f"""
        WITH Monthly AS (
            SELECT
                DATEFROMPARTS(YEAR(i.snapshot_date), MONTH(i.snapshot_date), 1) AS month_start,
                c.brand,
                SUM(i.available_qty) AS available_qty,
                SUM(i.inventory_value) AS inventory_value,
                SUM(CASE WHEN i.stock_status IN ('Low Stock', 'Reorder') THEN 1 ELSE 0 END) AS risk_count
            FROM khPriority.dbo.Inventory_TestData i
            INNER JOIN khPriority.dbo.Catalog_TestData c
                ON c.sku = i.sku AND c.org_id = i.org_id
            WHERE i.snapshot_date >= DATEADD(MONTH, -{int(months) - 1}, DATEFROMPARTS(YEAR(?), MONTH(?), 1)){org_filter}
            GROUP BY DATEFROMPARTS(YEAR(i.snapshot_date), MONTH(i.snapshot_date), 1), c.brand
        )
        SELECT
            month_start,
            SUM(available_qty) AS available_qty,
            SUM(inventory_value) AS inventory_value,
            SUM(risk_count) AS risk_count
        FROM Monthly
        GROUP BY month_start
        ORDER BY month_start
        """,
        params,
    )

    return {
        "labels": [row["month_start"].strftime("%b %Y") for row in rows],
        "keys": [row["month_start"].strftime("%Y-%m") for row in rows],
        "available": [round(_num(row.get("available_qty")), 0) for row in rows],
        "value": [round(_num(row.get("inventory_value")), 2) for row in rows],
        "risk": [round(_num(row.get("risk_count")), 0) for row in rows],
    }


def get_inventory_dashboard_context(org_id=None, snapshot_date=None, filters=None):
    filters = filters or {}
    rows, snapshot_date = _latest_inventory_rows(org_id, snapshot_date, filters)
    sales_map = _sales_by_style(org_id, snapshot_date)
    products = _enrich_inventory_rows(rows, sales_map)

    total_products = len(products)
    critical_count = sum(1 for row in products if row["risk_level"] == "Critical")
    reorder_count = sum(1 for row in products if row["risk_level"] in ("Reorder", "Velocity Risk"))
    overstock_count = sum(1 for row in products if row["risk_level"] == "Overstock")
    risk_products = critical_count + reorder_count
    healthy_count = sum(1 for row in products if row["risk_level"] == "Healthy")
    total_available = round(sum(_num(row.get("available_qty")) for row in products), 0)
    total_reserved = round(sum(_num(row.get("reserved_qty")) for row in products), 0)
    total_in_transit = round(sum(_num(row.get("in_transit_qty")) for row in products), 0)
    inventory_value = round(sum(_num(row.get("inventory_value")) for row in products), 2)
    sales_qty_90 = round(sum(_num(row.get("sales_qty_90")) for row in products), 0)
    net_sales_90 = round(sum(_num(row.get("net_sales_90")) for row in products), 2)
    avg_margin = round(
        (sum(_num(row.get("profit_90")) for row in products) / net_sales_90) * 100,
        1,
    ) if net_sales_90 else 0
    health_score = round(((healthy_count + overstock_count * 0.55 + reorder_count * 0.35) / max(total_products, 1)) * 100, 1)

    products_sorted = sorted(products, key=lambda row: (row["risk_score"], _num(row.get("sales_qty_90"))), reverse=True)
    brand_summary = _group_summary(products, "brand")
    category_summary = _group_summary(products, "category")
    status_summary = _group_summary(products, "stock_status")
    trend = _inventory_trend(org_id)

    def modal_rows(predicate):
        return [p for p in products_sorted if predicate(p)]

    kpi_details = {
        "available": {
            "title": "Available Inventory",
            "subtitle": "Current available quantity with reserve pressure and cover days.",
            "rows": sorted(products, key=lambda r: _num(r.get("available_qty")), reverse=True),
        },
        "inventory_value": {
            "title": "Inventory Value",
            "subtitle": "Products sorted by stock value on the latest snapshot.",
            "rows": sorted(products, key=lambda r: _num(r.get("inventory_value")), reverse=True),
        },
        "critical": {
            "title": "Critical Inventory",
            "subtitle": "Items at or below safety stock.",
            "rows": modal_rows(lambda r: r["risk_level"] == "Critical"),
        },
        "reorder": {
            "title": "Reorder and Velocity Risk",
            "subtitle": "Items below reorder point or with less than 14 days of cover.",
            "rows": modal_rows(lambda r: r["risk_level"] in ("Reorder", "Velocity Risk")),
        },
        "overstock": {
            "title": "Overstock Items",
            "subtitle": "Items flagged as overstock in the inventory snapshot.",
            "rows": modal_rows(lambda r: r["risk_level"] == "Overstock"),
        },
        "sales_velocity": {
            "title": "Sales Velocity",
            "subtitle": "Ninety-day sales quantity connected to current stock.",
            "rows": sorted(products, key=lambda r: _num(r.get("sales_qty_90")), reverse=True),
        },
    }

    recommendations = []
    if critical_count:
        recommendations.append(f"Resolve {critical_count} critical product(s) first; each is at or below safety stock.")
    if reorder_count:
        recommendations.append(f"Review {reorder_count} reorder/velocity-risk product(s) against incoming stock before new purchase decisions.")
    if total_in_transit:
        recommendations.append(f"{total_in_transit:,.0f} units are in transit; compare ETA with cover days before escalating replenishment.")
    if overstock_count:
        recommendations.append(f"{overstock_count} overstock product(s) can support promotions, bundles, or email recommendations.")
    if not recommendations:
        recommendations.append("Inventory is balanced for the selected filters. Keep watching reserve pressure and fast movers.")

    return {
        "snapshot_date": snapshot_date,
        "filters": filters,
        "summary": {
            "total_products": total_products,
            "health_score": health_score,
            "total_available": total_available,
            "total_reserved": total_reserved,
            "total_in_transit": total_in_transit,
            "inventory_value": inventory_value,
            "critical_count": critical_count,
            "reorder_count": reorder_count,
            "overstock_count": overstock_count,
            "risk_products": risk_products,
            "sales_qty_90": sales_qty_90,
            "net_sales_90": net_sales_90,
            "avg_margin": avg_margin,
        },
        "products": products_sorted,
        "brand_summary": brand_summary,
        "category_summary": category_summary,
        "status_summary": status_summary,
        "trend": trend,
        "recommendations": recommendations,
        "kpi_details": kpi_details,
    }


def get_inventory_point_detail(point_type, value, org_id=None, snapshot_date=None, filters=None):
    context = get_inventory_dashboard_context(org_id=org_id, snapshot_date=snapshot_date, filters=filters)
    products = context["products"]

    if point_type == "brand":
        rows = [row for row in products if str(row.get("brand")) == str(value)]
        title = f"{value} Detail"
        subtitle = "Brand-level inventory, sales velocity, margin, and risk."
    elif point_type == "category":
        rows = [row for row in products if str(row.get("category")) == str(value)]
        title = f"{value} Category"
        subtitle = "Category-level stock and risk detail."
    elif point_type == "status":
        rows = [row for row in products if str(row.get("stock_status")) == str(value)]
        title = f"{value} Products"
        subtitle = "Products matching this stock status."
    elif point_type == "sku":
        rows = [row for row in products if str(row.get("sku")) == str(value)]
        title = value
        subtitle = "Single product inventory profile."
    elif point_type == "month":
        rows = _inventory_month_detail(value, org_id=org_id)
        title = f"{value} Trend Detail"
        subtitle = "Monthly aggregate inventory position by product."
    elif point_type == "kpi":
        detail = context["kpi_details"].get(value, {})
        rows = detail.get("rows", [])
        title = detail.get("title", "KPI Detail")
        subtitle = detail.get("subtitle", "")
    else:
        rows = products
        title = "Inventory Detail"
        subtitle = "Current filtered inventory rows."

    return {
        "success": True,
        "title": title,
        "subtitle": subtitle,
        "rows": rows,
        "row_count": len(rows),
    }


def _inventory_month_detail(month_key, org_id=None):
    params = [f"{month_key}-01"]
    org_filter = _org_clause(org_id, "i")
    if org_id:
        params.append(org_id)

    return _inventory_rows(
        f"""
        SELECT
            c.brand,
            c.product_name,
            c.category,
            c.image_url,
            i.style_code,
            i.sku,
            SUM(i.available_qty) AS available_qty,
            SUM(i.reserved_qty) AS reserved_qty,
            SUM(i.in_transit_qty) AS in_transit_qty,
            SUM(i.inventory_value) AS inventory_value,
            MAX(i.stock_status) AS stock_status,
            AVG(CAST(i.reorder_point AS FLOAT)) AS reorder_point,
            AVG(CAST(i.safety_stock_qty AS FLOAT)) AS safety_stock_qty
        FROM khPriority.dbo.Inventory_TestData i
        INNER JOIN khPriority.dbo.Catalog_TestData c
            ON c.sku = i.sku AND c.org_id = i.org_id
        WHERE DATEFROMPARTS(YEAR(i.snapshot_date), MONTH(i.snapshot_date), 1) = ?{org_filter}
        GROUP BY c.brand, c.product_name, c.category, c.image_url, i.style_code, i.sku
        ORDER BY inventory_value DESC
        """,
        params,
    )
