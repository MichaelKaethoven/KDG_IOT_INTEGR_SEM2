import os
from functools import wraps
from urllib.parse import urlparse
from flask import Blueprint, render_template, request, session, redirect, url_for, abort
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash
from extensions import limiter
from db import get_db

auth_bp = Blueprint("auth", __name__)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "role" not in session:
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "role" not in session:
            return redirect(url_for("auth.login", next=request.url))
        if session["role"] != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


def current_customer_id():
    """Customer id this session is scoped to, or None for admin/user (no scope)."""
    if session.get("role") == "customer":
        return session.get("customer_id")
    return None


def _staff_login_ids() -> dict:
    """Map of configured staff login_id (lower-cased) -> role.

    Read at request time so env changes/tests apply without re-import, mirroring
    how the password hashes are read below. Defaults are the demo identifiers.
    """
    return {
        os.environ.get("ADMIN_LOGIN_ID", "admin@demo.local").strip().lower(): "admin",
        os.environ.get("USER_LOGIN_ID", "user@demo.local").strip().lower(): "user",
    }


def _match_staff(login_id: str, password: str):
    """Resolve a staff login to 'admin'/'user', or None.

    Staff may sign in with their configured login_id (admin@demo.local /
    user@demo.local by default) or leave the field blank — the legacy path, kept
    working because there is only ever one of each role. Either way the password
    is checked against that role's env-configured hash. Staff identifiers take
    precedence over customer login_ids, so they are effectively reserved.
    """
    hashes = {
        "admin": os.environ.get("ADMIN_PASSWORD_HASH", ""),
        "user": os.environ.get("USER_PASSWORD_HASH", ""),
    }
    lid = login_id.strip().lower()
    if not lid:
        # Blank login_id: match by password alone against either staff hash.
        if check_password_hash(hashes["admin"], password):
            return "admin"
        if check_password_hash(hashes["user"], password):
            return "user"
        return None
    role = _staff_login_ids().get(lid)
    if role and check_password_hash(hashes[role], password):
        return role
    return None


def _lookup_customer(login_id: str):
    """Resolve a customer by their explicit login_id (one indexed lookup).

    Replaces the legacy password-only scan that walked every customers row and
    silently cross-authenticated on hash collisions (see plan 10.5).
    """
    if not login_id:
        return None
    db = get_db()
    rows = (
        db.table("customers")
        .select("id, name, password_hash")
        .eq("login_id", login_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _is_safe_next(next_url: str) -> bool:
    """Allow only same-origin relative paths. Blocks //evil.com, /\\evil.com,
    and any URL with a netloc (covers absolute URLs)."""
    if not next_url:
        return False
    if not next_url.startswith("/") or next_url.startswith("//") or next_url.startswith("/\\"):
        return False
    parsed = urlparse(next_url)
    return not parsed.netloc and not parsed.scheme


def _login_key():
    """Rate-limit key: per-IP + submitted login_id, so brute force against one
    account doesn't burn another's quota and an attacker can't bypass by
    rotating identifiers from the same IP."""
    ip = get_remote_address() or "?"
    login_id = (request.form.get("login_id") or "").strip().lower() if request.method == "POST" else ""
    return f"{ip}|{login_id}"


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
@limiter.limit("5 per minute", key_func=_login_key, methods=["POST"])
def login():
    error = None
    if request.method == "POST":
        login_id = (request.form.get("login_id") or "").strip()
        password = request.form.get("password", "")

        # Staff first (explicit login_id or blank legacy path); a submitted
        # login_id that isn't a staff account falls through to customer lookup.
        staff_role = _match_staff(login_id, password)
        if staff_role:
            session["role"] = staff_role
        elif login_id:
            customer = _lookup_customer(login_id)
            if customer and customer["password_hash"] \
                    and check_password_hash(customer["password_hash"], password):
                session["role"] = "customer"
                session["customer_id"] = customer["id"]
                session["customer_name"] = customer["name"]
            else:
                error = "Invalid credentials."
        else:
            error = "Invalid credentials."

        if "role" in session:
            session.permanent = True
            next_url = request.args.get("next", "")
            if not _is_safe_next(next_url):
                next_url = url_for("dashboard.index")
            return redirect(next_url)

    return render_template("login.html", error=error)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.app_errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403
