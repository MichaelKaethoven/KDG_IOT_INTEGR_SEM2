from flask import Blueprint, render_template, current_app, request
from blueprints.auth import login_required
from db import get_db

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    db = get_db()
    customer_id = request.args.get("customer", "all")
    order_id    = request.args.get("order", "all")
    tracker_id  = request.args.get("tracker", "all")
    view        = request.args.get("view", "current")

    if view not in ("current", "historical"):
        view = "current"

    customers = db.table("customers").select("id, name").order("name").execute().data
    all_orders = db.table("orders").select("id, customer_id, order_date, status").order("order_date", desc=True).execute().data

    orders = [o for o in all_orders if customer_id == "all" or o["customer_id"] == customer_id]

    # Fetch trackers active for the current customer/order scope
    assignments = (
        db.table("order_trackers")
        .select("tracker_id, order_id")
        .is_("removed_at", "null")
        .execute()
        .data
    )

    if order_id != "all":
        valid_order_ids = {order_id}
    elif customer_id != "all":
        valid_order_ids = {o["id"] for o in orders}
    else:
        valid_order_ids = None

    valid_tracker_ids = list({
        a["tracker_id"] for a in assignments
        if valid_order_ids is None or a["order_id"] in valid_order_ids
    })

    if valid_tracker_ids:
        trackers = (
            db.table("trackers")
            .select("id, device_name")
            .in_("id", valid_tracker_ids)
            .order("device_name")
            .execute()
            .data
        )
    else:
        trackers = []

    grafana_url = current_app.config["GRAFANA_URL"]
    iframe_src = (
        f"{grafana_url}/d/tracker-locations/tracker-dashboard"
        f"?var-customer={customer_id}"
        f"&var-order_var={order_id}"
        f"&var-tracker={tracker_id}"
        f"&var-view={view}"
        f"&kiosk&theme=light"
    )

    return render_template(
        "dashboard.html",
        customers=customers,
        orders=orders,
        trackers=trackers,
        selected_customer=customer_id,
        selected_order=order_id,
        selected_tracker=tracker_id,
        selected_view=view,
        iframe_src=iframe_src,
    )
