from flask import Blueprint, jsonify, render_template
from flask_login import login_required

from app.sales_analysis.service import get_ups_heatmap_data, get_ups_sales_match_data


sales_analysis_bp = Blueprint("sales_analysis", __name__, url_prefix="/sales-analysis")


@sales_analysis_bp.route("/heatmap")
@login_required
def heatmap():
    heatmap_data = get_ups_heatmap_data()
    return render_template("sales_analysis/heatmap.html", heatmap_data=heatmap_data)


@sales_analysis_bp.route("/heatmap/sales-match")
@login_required
def heatmap_sales_match():
    return jsonify(get_ups_sales_match_data())
