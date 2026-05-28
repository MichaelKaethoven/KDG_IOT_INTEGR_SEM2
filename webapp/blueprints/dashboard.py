from flask import Blueprint, render_template, current_app, request
from blueprints.auth import login_required, current_customer_id
from db import get_db

dashboard_bp = Blueprint("dashboard", __name__)

# Time ranges offered for the historical map. Keys are the URL/form values; the
# Grafana value is a relative-time expression Grafana understands as `from`
# (paired with `to=now`). Allow-listed so nothing user-controlled is interpolated
# verbatim into the iframe URL.
TIME_RANGE_OPTIONS = [
    ("1h", "Last 1 hour", "now-1h"),
    ("6h", "Last 6 hours", "now-6h"),
    ("24h", "Last 24 hours", "now-24h"),
    ("7d", "Last 7 days", "now-7d"),
    ("30d", "Last 30 days", "now-30d"),
    ("90d", "Last 90 days", "now-90d"),
]
TIME_RANGE_FROM = {key: gf for key, _, gf in TIME_RANGE_OPTIONS}
DEFAULT_RANGE = "24h"


@dashboard_bp.route("/")
@login_required
def index():
    db = get_db()
    scope_id = current_customer_id()
    # Customer-scoped sessions can't change the customer filter — pin to themselves.
    customer_id = scope_id if scope_id else request.args.get("customer", "all")
    order_id    = request.args.get("order", "all")
    tracker_id  = request.args.get("tracker", "all")
    view        = request.args.get("view", "current")
    time_range  = request.args.get("range", DEFAULT_RANGE)

    if view not in ("current", "historical"):
        view = "current"
    if time_range not in TIME_RANGE_FROM:
        time_range = DEFAULT_RANGE

    if scope_id:
        customers = (
            db.table("customers").select("id, name").eq("id", scope_id).execute().data
        )
    else:
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
        f"&from={TIME_RANGE_FROM[time_range]}&to=now"
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
        selected_range=time_range,
        time_range_options=TIME_RANGE_OPTIONS,
        iframe_src=iframe_src,
        customer_locked=bool(scope_id),
    )
