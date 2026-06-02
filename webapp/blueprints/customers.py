from flask import Blueprint, render_template, request, redirect, url_for, abort, flash
from werkzeug.security import generate_password_hash
from blueprints.auth import login_required, admin_required, current_customer_id
from db import get_db
from pagination import parse_page, build_pagination

# Columns we expose to templates. Explicitly excludes `password_hash` so the
# hash never reaches the browser via a list/detail response.
_CUSTOMER_COLS = "id, name, email, phone, color_idx, login_id, created_at"


def _clean_login_id(raw: str | None) -> str | None:
    """Normalize: trim, collapse to None when blank. Case is preserved so
    operators can choose readable IDs (e.g. 'Acme-EU')."""
    value = (raw or "").strip()
    return value or None

customers_bp = Blueprint("customers", __name__)

# Fixed palette — must stay in lock-step with the customer_color_idx thresholds
# in grafana/provisioning/dashboards/trackers.json. Index = step value.
CUSTOMER_PALETTE = [
    {"idx": 0, "hex": "#E84142", "name": "Red"},
    {"idx": 1, "hex": "#1F77B4", "name": "Blue"},
    {"idx": 2, "hex": "#2CA02C", "name": "Green"},
    {"idx": 3, "hex": "#FF7F0E", "name": "Orange"},
    {"idx": 4, "hex": "#9467BD", "name": "Purple"},
    {"idx": 5, "hex": "#FFD700", "name": "Gold"},
    {"idx": 6, "hex": "#E377C2", "name": "Pink"},
    {"idx": 7, "hex": "#17BECF", "name": "Cyan"},
    {"idx": 8, "hex": "#8C564B", "name": "Brown"},
    {"idx": 9, "hex": "#7F7F7F", "name": "Gray"},
]


def _parse_color_idx(value: str | None) -> int:
    try:
        idx = int(value) if value is not None else 0
    except (TypeError, ValueError):
        idx = 0
    return idx if 0 <= idx < len(CUSTOMER_PALETTE) else 0


@customers_bp.route("/")
@login_required
def list_customers():
    db = get_db()
    # A customer-scoped session only ever sees its own record on this page.
    scope_id = current_customer_id()
    if scope_id:
        return redirect(url_for("customers.customer_detail", customer_id=scope_id))

    search = request.args.get("q", "").strip()
    offset, last_idx, page_size = parse_page()
    query = db.table("customers").select(_CUSTOMER_COLS).order("name")
    if search:
        query = query.ilike("name", f"%{search}%")
    customers = query.range(offset, last_idx).execute().data

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

    return render_template(
        "customers/list.html",
        customers=customers,
        search=search,
        palette=CUSTOMER_PALETTE,
        pagination=build_pagination(page_size, len(customers)),
    )


@customers_bp.route("/new", methods=["GET", "POST"])
@admin_required
def new_customer():
    if request.method == "POST":
        db = get_db()
        login_id = _clean_login_id(request.form.get("login_id"))
        if login_id and _login_id_taken(db, login_id, exclude_id=None):
            flash(f"Login ID '{login_id}' is already in use.", "danger")
            return render_template(
                "customers/form.html", customer=None, palette=CUSTOMER_PALETTE,
            ), 400
        payload = {
            "name": request.form["name"],
            "email": request.form.get("email") or None,
            "phone": request.form.get("phone") or None,
            "color_idx": _parse_color_idx(request.form.get("color_idx")),
            "login_id": login_id,
        }
        new_password = request.form.get("password", "").strip()
        if new_password:
            payload["password_hash"] = generate_password_hash(new_password)
        db.table("customers").insert(payload).execute()
        return redirect(url_for("customers.list_customers"))
    return render_template("customers/form.html", customer=None, palette=CUSTOMER_PALETTE)


def _login_id_taken(db, login_id: str, exclude_id: str | None) -> bool:
    query = db.table("customers").select("id").eq("login_id", login_id).limit(1)
    rows = query.execute().data
    if not rows:
        return False
    return rows[0]["id"] != exclude_id


@customers_bp.route("/<customer_id>")
@login_required
def customer_detail(customer_id):
    scope_id = current_customer_id()
    if scope_id and scope_id != customer_id:
        abort(403)

    db = get_db()
    customer = db.table("customers").select(_CUSTOMER_COLS).eq("id", customer_id).single().execute().data
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

    return render_template(
        "customers/detail.html",
        customer=customer,
        orders=orders,
        palette=CUSTOMER_PALETTE,
    )


@customers_bp.route("/<customer_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_customer(customer_id):
    db = get_db()
    customer = db.table("customers").select(_CUSTOMER_COLS).eq("id", customer_id).single().execute().data
    if request.method == "POST":
        login_id = _clean_login_id(request.form.get("login_id"))
        if login_id and _login_id_taken(db, login_id, exclude_id=customer_id):
            flash(f"Login ID '{login_id}' is already in use.", "danger")
            return render_template(
                "customers/form.html", customer=customer, palette=CUSTOMER_PALETTE,
            ), 400
        payload = {
            "name": request.form["name"],
            "email": request.form.get("email") or None,
            "phone": request.form.get("phone") or None,
            "color_idx": _parse_color_idx(request.form.get("color_idx")),
            "login_id": login_id,
        }
        new_password = request.form.get("password", "").strip()
        if new_password:
            payload["password_hash"] = generate_password_hash(new_password)
        db.table("customers").update(payload).eq("id", customer_id).execute()
        return redirect(url_for("customers.customer_detail", customer_id=customer_id))
    return render_template("customers/form.html", customer=customer, palette=CUSTOMER_PALETTE)


@customers_bp.route("/<customer_id>/delete", methods=["POST"])
@admin_required
def delete_customer(customer_id):
    db = get_db()
    db.table("customers").delete().eq("id", customer_id).execute()
    return redirect(url_for("customers.list_customers"))
