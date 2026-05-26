from flask import Blueprint, render_template, request, redirect, url_for
from blueprints.auth import login_required, admin_required
from db import get_db

customers_bp = Blueprint("customers", __name__)


@customers_bp.route("/")
@login_required
def list_customers():
    db = get_db()
    search = request.args.get("q", "").strip()
    query = db.table("customers").select("*").order("name")
    if search:
        query = query.ilike("name", f"%{search}%")
    customers = query.execute().data

    # One round-trip: pull every active order_tracker with its order's customer_id.
    active = (
        db.table("order_trackers")
        .select("id, order:orders!inner(customer_id)")
        .is_("removed_at", "null")
        .execute()
        .data
    )
    counts: dict = {}
    for row in active:
        cid = row["order"]["customer_id"]
        counts[cid] = counts.get(cid, 0) + 1
    for customer in customers:
        customer["active_trackers"] = counts.get(customer["id"], 0)

    return render_template("customers/list.html", customers=customers, search=search)


@customers_bp.route("/new", methods=["GET", "POST"])
@admin_required
def new_customer():
    if request.method == "POST":
        db = get_db()
        db.table("customers").insert({
            "name": request.form["name"],
            "email": request.form.get("email") or None,
            "phone": request.form.get("phone") or None,
        }).execute()
        return redirect(url_for("customers.list_customers"))
    return render_template("customers/form.html", customer=None)


@customers_bp.route("/<customer_id>")
@login_required
def customer_detail(customer_id):
    db = get_db()
    customer = db.table("customers").select("*").eq("id", customer_id).single().execute().data
    orders = (
        db.table("orders")
        .select("*")
        .eq("customer_id", customer_id)
        .order("order_date", desc=True)
        .execute()
        .data
    )
    # One round-trip: count active trackers per order in Python.
    order_ids = [o["id"] for o in orders]
    counts: dict = {}
    if order_ids:
        active = (
            db.table("order_trackers")
            .select("order_id")
            .in_("order_id", order_ids)
            .is_("removed_at", "null")
            .execute()
            .data
        )
        for row in active:
            oid = row["order_id"]
            counts[oid] = counts.get(oid, 0) + 1
    for order in orders:
        order["assigned_count"] = counts.get(order["id"], 0)

    return render_template("customers/detail.html", customer=customer, orders=orders)


@customers_bp.route("/<customer_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_customer(customer_id):
    db = get_db()
    customer = db.table("customers").select("*").eq("id", customer_id).single().execute().data
    if request.method == "POST":
        db.table("customers").update({
            "name": request.form["name"],
            "email": request.form.get("email") or None,
            "phone": request.form.get("phone") or None,
        }).eq("id", customer_id).execute()
        return redirect(url_for("customers.customer_detail", customer_id=customer_id))
    return render_template("customers/form.html", customer=customer)


@customers_bp.route("/<customer_id>/delete", methods=["POST"])
@admin_required
def delete_customer(customer_id):
    db = get_db()
    db.table("customers").delete().eq("id", customer_id).execute()
    return redirect(url_for("customers.list_customers"))
