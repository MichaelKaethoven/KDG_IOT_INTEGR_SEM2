from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from blueprints.auth import login_required, admin_required, current_customer_id
from db import get_db
from pagination import parse_page, build_pagination

_ORDER_COLS = "id, customer_id, status, quantity, order_date, notes, created_at"
# Side-loaded customer fields. Explicit so password_hash never tags along.
_ORDER_CUSTOMER_COLS = "id, name, email, phone, color_idx"


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

VALID_TRANSITIONS = {
    "pending":   {"active", "cancelled"},
    "active":    {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
TERMINAL_STATUSES = {"completed", "cancelled"}


def _valid_next_statuses(current: str) -> list:
    """Statuses the dropdown should offer: the current status plus any valid
    forward transitions. Terminal orders only show their current status."""
    options = {current} | VALID_TRANSITIONS.get(current, set())
    return [s for s in STATUSES if s in options]


@orders_bp.route("/")
@login_required
def list_orders():
    db = get_db()
    scope_id = current_customer_id()
    # Customer-scoped sessions can't widen the filter to other customers.
    customer_id = scope_id or request.args.get("customer", "")
    status = request.args.get("status", "")

    offset, last_idx, page_size = parse_page()
    query = (
        db.table("orders")
        .select(f"{_ORDER_COLS}, customer:customers(id, name)")
        .order("order_date", desc=True)
    )
    if customer_id:
        query = query.eq("customer_id", customer_id)
    if status:
        query = query.eq("status", status)
    orders = query.range(offset, last_idx).execute().data

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
        pagination=build_pagination(page_size, len(orders)),
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
        .select(f"{_ORDER_COLS}, customer:customers({_ORDER_CUSTOMER_COLS})")
        .eq("id", order_id)
        .single()
        .execute()
        .data
    )
    scope_id = current_customer_id()
    if scope_id and order["customer_id"] != scope_id:
        abort(403)

    assignments = (
        db.table("order_trackers")
        .select("*, tracker:trackers(*)")
        .eq("order_id", order_id)
        .is_("removed_at", "null")
        .execute()
        .data
    )

    # One round-trip via the latest_device_locations view for all assigned
    # trackers. Avoids one query per assignment (was N+1). See plan 10.7.
    device_names = [a["tracker"]["device_name"] for a in assignments if a.get("tracker")]
    latest_by_device: dict = {}
    if device_names:
        locs = (
            db.table("latest_device_locations")
            .select("device_name, lat, lon, time")
            .in_("device_name", device_names)
            .execute()
            .data
        )
        for row in locs:
            latest_by_device[row["device_name"]] = {
                "lat": row["lat"], "lon": row["lon"], "time": row["time"],
            }
    for a in assignments:
        a["last_location"] = latest_by_device.get(a["tracker"]["device_name"]) if a.get("tracker") else None

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
        valid_statuses=_valid_next_statuses(order["status"]),
        is_terminal=order["status"] in TERMINAL_STATUSES,
    )


@orders_bp.route("/<order_id>/edit", methods=["POST"])
@admin_required
def edit_order(order_id):
    db = get_db()
    quantity = _parse_quantity(request.form.get("quantity"))
    if quantity is None:
        flash("Quantity must be a positive integer.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order_id))

    order = db.table("orders").select("status").eq("id", order_id).single().execute().data
    current_status = order["status"]
    new_status = request.form.get("status", current_status)
    notes = request.form.get("notes") or None

    if current_status in TERMINAL_STATUSES:
        flash("This order is closed and cannot be changed.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order_id))

    if new_status != current_status and new_status not in VALID_TRANSITIONS.get(current_status, set()):
        flash(f"Cannot transition from {current_status} to {new_status}.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order_id))

    if new_status != current_status and new_status in TERMINAL_STATUSES:
        # Persist the editable fields now; defer status flip + tracker release
        # to the confirmation step so the admin can review what gets released.
        db.table("orders").update({
            "quantity": quantity,
            "notes": notes,
        }).eq("id", order_id).execute()
        return redirect(url_for(
            "orders.confirm_release",
            order_id=order_id,
            next_status=new_status,
        ))

    db.table("orders").update({
        "status": new_status,
        "quantity": quantity,
        "notes": notes,
    }).eq("id", order_id).execute()
    return redirect(url_for("orders.order_detail", order_id=order_id))


@orders_bp.route("/<order_id>/confirm-release", methods=["GET", "POST"])
@admin_required
def confirm_release(order_id):
    db = get_db()
    next_status = (request.values.get("next_status") or "").lower()
    if next_status not in TERMINAL_STATUSES:
        flash("Invalid target status.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order_id))

    order = (
        db.table("orders")
        .select(f"{_ORDER_COLS}, customer:customers(id, name)")
        .eq("id", order_id)
        .single()
        .execute()
        .data
    )
    if order["status"] in TERMINAL_STATUSES:
        flash("This order is already closed.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order_id))
    if next_status not in VALID_TRANSITIONS.get(order["status"], set()):
        flash(
            f"Cannot transition from {order['status']} to {next_status}.",
            "warning",
        )
        return redirect(url_for("orders.order_detail", order_id=order_id))

    active = (
        db.table("order_trackers")
        .select("tracker_id, tracker:trackers(device_name, serial_number)")
        .eq("order_id", order_id)
        .is_("removed_at", "null")
        .execute()
        .data
    )

    if request.method == "POST":
        if active:
            db.table("order_trackers").update({
                "removed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("order_id", order_id).is_("removed_at", "null").execute()
        db.table("orders").update({"status": next_status}).eq("id", order_id).execute()
        flash(
            f"Order marked {next_status}; released {len(active)} tracker(s).",
            "success",
        )
        return redirect(url_for("orders.order_detail", order_id=order_id))

    return render_template(
        "orders/confirm_release.html",
        order=order,
        active=active,
        next_status=next_status,
    )


@orders_bp.route("/<order_id>/assign", methods=["POST"])
@admin_required
def assign_tracker(order_id):
    db = get_db()
    tracker_ids = request.form.getlist("tracker_ids") or (
        [request.form["tracker_id"]] if request.form.get("tracker_id") else []
    )
    if not tracker_ids:
        flash("Select at least one tracker to assign.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order_id))

    order = (
        db.table("orders").select("quantity").eq("id", order_id).single().execute().data
    )
    current_assigned = (
        db.table("order_trackers")
        .select("tracker_id", count="exact")
        .eq("order_id", order_id)
        .is_("removed_at", "null")
        .execute()
        .count
    ) or 0
    if order and current_assigned + len(tracker_ids) > order["quantity"]:
        flash(
            f"Warning: assigning {len(tracker_ids)} would exceed the order quantity "
            f"({current_assigned + len(tracker_ids)} > {order['quantity']}).",
            "warning",
        )

    rows = [{"order_id": order_id, "tracker_id": tid} for tid in tracker_ids]
    db.table("order_trackers").insert(rows).execute()
    flash(f"Assigned {len(rows)} tracker(s) to this order.", "success")
    return redirect(url_for("orders.order_detail", order_id=order_id))


@orders_bp.route("/<order_id>/trackers/<tracker_id>/remove", methods=["POST"])
@admin_required
def remove_tracker(order_id, tracker_id):
    db = get_db()
    db.table("order_trackers").update({
        "removed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("order_id", order_id).eq("tracker_id", tracker_id).is_("removed_at", "null").execute()
    return redirect(url_for("orders.order_detail", order_id=order_id))


@orders_bp.route("/<order_id>/remove-bulk", methods=["POST"])
@admin_required
def remove_trackers_bulk(order_id):
    tracker_ids = request.form.getlist("tracker_ids")
    if not tracker_ids:
        flash("Select at least one tracker to remove.", "warning")
        return redirect(url_for("orders.order_detail", order_id=order_id))
    db = get_db()
    db.table("order_trackers").update({
        "removed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("order_id", order_id).in_("tracker_id", tracker_ids).is_(
        "removed_at", "null"
    ).execute()
    flash(f"Removed {len(tracker_ids)} tracker(s) from this order.", "success")
    return redirect(url_for("orders.order_detail", order_id=order_id))
