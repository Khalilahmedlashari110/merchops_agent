from app.database.connection_manager import get_master_connection
from app.inventory.service import get_presentation_batches, compare_presentation_batches, get_presentation_rows_from_db


def get_latest_two_batches():
    batches = get_presentation_batches()
    if len(batches) < 2:
        return None, None
    return batches[0], batches[1]


def build_inventory_alerts_from_comparison(old_batch_id, new_batch_id):
    comparisons = compare_presentation_batches(old_batch_id, new_batch_id)
    alerts = []

    risk_rank = {
        "Safe": 1,
        "Low Coverage": 2,
        "New Order Required": 3,
        "High Risk": 4,
        "Critical": 5,
        "Out of Stock": 6
    }

    for row in comparisons:
        sku = row.get("SKU")
        distributor = row.get("Distributor")
        brand = row.get("Brand")
        style = row.get("Style")
        colour = row.get("Colour")
        ssize = row.get("SSize")

        old_available = float(row.get("OldAvailableQty", 0) or 0)
        new_available = float(row.get("NewAvailableQty", 0) or 0)
        old_cov = float(row.get("OldCoveragePct", 0) or 0)
        new_cov = float(row.get("NewCoveragePct", 0) or 0)
        old_req = float(row.get("OldReqNewOrderQty", 0) or 0)
        new_req = float(row.get("NewReqNewOrderQty", 0) or 0)
        old_risk = str(row.get("OldRiskStatus") or "")
        new_risk = str(row.get("NewRiskStatus") or "")

        # Out of stock
        if new_available <= 0 and old_available > 0:
            alerts.append({
                "alert_type": "Out of Stock",
                "severity": "Critical",
                "Distributor": distributor,
                "Brand": brand,
                "Style": style,
                "Colour": colour,
                "SSize": ssize,
                "SKU": sku,
                "old_value": old_available,
                "new_value": new_available,
                "message": f"{sku} has moved to out of stock."
            })

        # Critical coverage
        if new_cov <= 20:
            alerts.append({
                "alert_type": "Critical Coverage",
                "severity": "Critical",
                "Distributor": distributor,
                "Brand": brand,
                "Style": style,
                "Colour": colour,
                "SSize": ssize,
                "SKU": sku,
                "old_value": old_cov,
                "new_value": new_cov,
                "message": f"{sku} coverage dropped to critical level ({new_cov}%)."
            })

        # Coverage dropped sharply
        if (old_cov - new_cov) >= 20:
            alerts.append({
                "alert_type": "Coverage Dropped",
                "severity": "High",
                "Distributor": distributor,
                "Brand": brand,
                "Style": style,
                "Colour": colour,
                "SSize": ssize,
                "SKU": sku,
                "old_value": old_cov,
                "new_value": new_cov,
                "message": f"{sku} coverage dropped from {old_cov}% to {new_cov}%."
            })

        # New order required increased
        if new_req > 0 and new_req > old_req:
            alerts.append({
                "alert_type": "New Order Required",
                "severity": "High",
                "Distributor": distributor,
                "Brand": brand,
                "Style": style,
                "Colour": colour,
                "SSize": ssize,
                "SKU": sku,
                "old_value": old_req,
                "new_value": new_req,
                "message": f"{sku} now requires new order quantity {new_req}."
            })

        # Risk escalated
        if risk_rank.get(new_risk, 0) > risk_rank.get(old_risk, 0):
            alerts.append({
                "alert_type": "Risk Escalated",
                "severity": "Medium",
                "Distributor": distributor,
                "Brand": brand,
                "Style": style,
                "Colour": colour,
                "SSize": ssize,
                "SKU": sku,
                "old_value": risk_rank.get(old_risk, 0),
                "new_value": risk_rank.get(new_risk, 0),
                "message": f"{sku} risk changed from {old_risk or 'None'} to {new_risk}."
            })

    return alerts


def save_inventory_alerts(batch_id, previous_batch_id, alerts):
    conn = get_master_connection()
    cursor = conn.cursor()

    # clear old unresolved alerts for same comparison pair
    cursor.execute("""
        DELETE FROM khPriority.dbo.InventoryAlerts
        WHERE batch_id = ? AND previous_batch_id = ? AND is_resolved = 0
    """, batch_id, previous_batch_id)

    for a in alerts:
        cursor.execute("""
            INSERT INTO khPriority.dbo.InventoryAlerts (
                batch_id,
                previous_batch_id,
                alert_type,
                severity,
                Distributor,
                Brand,
                Style,
                Colour,
                SSize,
                SKU,
                old_value,
                new_value,
                message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            batch_id,
            previous_batch_id,
            a.get("alert_type"),
            a.get("severity"),
            a.get("Distributor"),
            a.get("Brand"),
            a.get("Style"),
            a.get("Colour"),
            a.get("SSize"),
            a.get("SKU"),
            a.get("old_value"),
            a.get("new_value"),
            a.get("message"),
        ))

    conn.commit()
    conn.close()


def generate_alerts_from_latest_batches():
    latest, previous = get_latest_two_batches()

    if not latest or not previous:
        return {
            "success": False,
            "message": "At least two saved batches are required to generate alerts."
        }

    alerts = build_inventory_alerts_from_comparison(
        old_batch_id=previous["upload_batch_id"],
        new_batch_id=latest["upload_batch_id"]
    )

    save_inventory_alerts(
        batch_id=latest["upload_batch_id"],
        previous_batch_id=previous["upload_batch_id"],
        alerts=alerts
    )

    return {
        "success": True,
        "message": f"{len(alerts)} alerts generated successfully.",
        "count": len(alerts),
        "latest_batch_id": latest["upload_batch_id"],
        "previous_batch_id": previous["upload_batch_id"]
    }


def get_inventory_alerts(show_resolved=False):
    conn = get_master_connection()
    cursor = conn.cursor()

    if show_resolved:
        cursor.execute("""
            SELECT *
            FROM khPriority.dbo.InventoryAlerts
            ORDER BY created_at DESC, id DESC
        """)
    else:
        cursor.execute("""
            SELECT *
            FROM khPriority.dbo.InventoryAlerts
            WHERE is_resolved = 0
            ORDER BY created_at DESC, id DESC
        """)

    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()

    return [dict(zip(columns, row)) for row in rows]


def resolve_inventory_alert(alert_id):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE khPriority.dbo.InventoryAlerts
        SET is_resolved = 1,
            resolved_at = GETDATE()
        WHERE id = ?
    """, alert_id)

    conn.commit()
    conn.close()


def get_alert_summary(alerts):
    return {
        "total_alerts": len(alerts),
        "critical_count": sum(1 for a in alerts if str(a.get("severity")) == "Critical"),
        "high_count": sum(1 for a in alerts if str(a.get("severity")) == "High"),
        "medium_count": sum(1 for a in alerts if str(a.get("severity")) == "Medium"),
    }

def get_top_50_high_sales_inventory(batch_id=None):
    rows = get_presentation_rows_from_db(batch_id)

    rows = sorted(
        rows,
        key=lambda r: (
            float(r.get("AvgMonthlySales6M", 0) or 0),
            -float(r.get("CoveragePct", 0) or 0)
        ),
        reverse=True
    )

    return rows[:50]