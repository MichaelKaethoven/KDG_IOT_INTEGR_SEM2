from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash
from blueprints.auth import login_required, admin_required
from db import get_db


def _parse_quantity(raw):
    try:
        quantity = int(raw)
    except (TypeError, ValueError):
        return None
    if quantity < 1:
        return None
    return quantity

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

    # One round-trip for all active assignments, grouped in Python.
    active = (
        db.table("order_trackers")
        .select("order_id")
        .is_("removed_at", "null")
        .execute()
        .data
    )
    counts: dict = {}
    for row in active:
        oid = row["order_id"]
        counts[oid] = counts.get(oid, 0) + 1
    for order in orders:
        order["assigned_count"] = counts.get(order["id"], 0)

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
        quantity = _parse_quantity(request.form.get("quantity"))
        if quantity is None:
            customers = db.table("customers").select("id, name").order("name").execute().data
            return render_template(
                "orders/form.html",
                order=None,
                customers=customers,
                statuses=STATUSES,
                error="Quantity must be a positive integer.",
            ), 400
        db.table("orders").insert({
            "customer_id": request.form["customer_id"],
            "quantity": quantity,
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
    quantity = _parse_quantity(request.form.get("quantity"))
    if quantity is None:
        flash("Quantity must be a positive integer.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order_id))
    db.table("orders").update({
        "status": request.form["status"],
        "quantity": quantity,
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
