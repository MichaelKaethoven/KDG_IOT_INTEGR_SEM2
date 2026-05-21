import os
from functools import wraps
from flask import Blueprint, render_template, request, session, redirect, url_for, abort

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
        if session.get("role") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == os.environ.get("ADMIN_PASSWORD"):
            session["role"] = "admin"
        elif password == os.environ.get("USER_PASSWORD"):
            session["role"] = "user"
        else:
            error = "Invalid password."

        if "role" in session:
            next_url = request.args.get("next") or url_for("dashboard.index")
            return redirect(next_url)

    return render_template("login.html", error=error)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.app_errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403
