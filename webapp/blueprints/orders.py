from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for
from blueprints.auth import login_required, admin_required
from db import get_db

orders_bp = Blueprint("orders", __name__)

STATUSES = ["pending", "active", "completed", "cancelled"]


@orders_bp.route("/")
@login_required
def list_orders():
    db = get_db()
    customer_id = request.args.get("customer", "")
    status = request.args.get("status", "")

    query = db.table("orders").select("*, customer:customers(id, name)").order("order_date", desc=True)
    if customer_id:
        query = query.eq("customer_id", customer_id)
    if status:
        query = query.eq("status", status)
    orders = query.execute().data

    # Attach assigned tracker count
    for order in orders:
        assigned = (
            db.table("order_trackers")
            .select("id")
            .eq("order_id", order["id"])
            .is_("removed_at", "null")
            .execute()
            .data
        )
        order["assigned_count"] = len(assigned)

    customers = db.table("customers").select("id, name").order("name").execute().data
    return render_template(
        "orders/list.html",
        orders=orders,
        customers=customers,
        selected_customer=customer_id,
        selected_status=status,
        statuses=STATUSES,
    )


@orders_bp.route("/new", methods=["GET", "POST"])
@admin_required
def new_order():
    db = get_db()
    if request.method == "POST":
        db.table("orders").insert({
            "customer_id": request.form["customer_id"],
            "quantity": int(request.form["quantity"]),
            "status": request.form.get("status", "pending"),
            "notes": request.form.get("notes") or None,
        }).execute()
        return redirect(url_for("orders.list_orders"))
    customers = db.table("customers").select("id, name").order("name").execute().data
    return render_template("orders/form.html", order=None, customers=customers, statuses=STATUSES)


@orders_bp.route("/<order_id>")
@login_required
def order_detail(order_id):
    db = get_db()
    order = (
        db.table("orders")
        .select("*, customer:customers(*)")
        .eq("id", order_id)
        .single()
        .execute()
        .data
    )

    assignments = (
        db.table("order_trackers")
        .select("*, tracker:trackers(*)")
        .eq("order_id", order_id)
        .is_("removed_at", "null")
        .execute()
        .data
    )

    for a in assignments:
        device_name = a["tracker"]["device_name"]
        loc = (
            db.table("device_locations")
            .select("lat, lon, time")
            .eq("device_name", device_name)
            .order("time", desc=True)
            .limit(1)
            .execute()
            .data
        )
        a["last_location"] = loc[0] if loc else None

    # Available trackers: not currently assigned anywhere
    all_trackers = db.table("trackers").select("*").order("device_name").execute().data
    active_assignments = (
        db.table("order_trackers").select("tracker_id").is_("removed_at", "null").execute().data
    )
    assigned_ids = {a["tracker_id"] for a in active_assignments}
    available_trackers = [t for t in all_trackers if t["id"] not in assigned_ids]

    return render_template(
        "orders/detail.html",
        order=order,
        assignments=assignments,
        fulfilled=len(assignments),
        available_trackers=available_trackers,
        statuses=STATUSES,
    )


@orders_bp.route("/<order_id>/edit", methods=["POST"])
@admin_required
def edit_order(order_id):
    db = get_db()
    db.table("orders").update({
        "status": request.form["status"],
        "quantity": int(request.form["quantity"]),
        "notes": request.form.get("notes") or None,
    }).eq("id", order_id).execute()
    return redirect(url_for("orders.order_detail", order_id=order_id))


@orders_bp.route("/<order_id>/assign", methods=["POST"])
@admin_required
def assign_tracker(order_id):
    db = get_db()
    tracker_id = request.form["tracker_id"]
    db.table("order_trackers").insert({
        "order_id": order_id,
        "tracker_id": tracker_id,
    }).execute()
    return redirect(url_for("orders.order_detail", order_id=order_id))


@orders_bp.route("/<order_id>/trackers/<tracker_id>/remove", methods=["POST"])
@admin_required
def remove_tracker(order_id, tracker_id):
    db = get_db()
    db.table("order_trackers").update({
        "removed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("order_id", order_id).eq("tracker_id", tracker_id).is_("removed_at", "null").execute()
    return redirect(url_for("orders.order_detail", order_id=order_id))
