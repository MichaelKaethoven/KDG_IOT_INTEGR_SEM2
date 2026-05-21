from flask import Blueprint, render_template, current_app, request, session
from blueprints.auth import login_required
from db import get_db

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    db = get_db()
    customer_id = request.args.get("customer", "all")
    order_id = request.args.get("order", "all")

    customers = db.table("customers").select("id, name").order("name").execute().data
    orders = db.table("orders").select("id, customer_id, order_date, status").order("order_date", desc=True).execute().data

    if customer_id != "all":
        orders = [o for o in orders if o["customer_id"] == customer_id]

    grafana_url = current_app.config["GRAFANA_URL"]
    iframe_src = (
        f"{grafana_url}/d/tracker-locations/tracker-dashboard"
        f"?var-customer={customer_id}&var-order_var={order_id}&kiosk&theme=light"
    )

    return render_template(
        "dashboard.html",
        customers=customers,
        orders=orders,
        selected_customer=customer_id,
        selected_order=order_id,
        iframe_src=iframe_src,
    )
