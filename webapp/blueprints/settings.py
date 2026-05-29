from flask import Blueprint, render_template, request, redirect, url_for, flash

from blueprints.auth import admin_required
from settings_store import SETTINGS_SPEC, get_settings, save_settings

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/", methods=["GET", "POST"])
@admin_required
def index():
    if request.method == "POST":
        errors = save_settings(request.form)
        if errors:
            # Re-render with the values the admin submitted so nothing is lost.
            values = {s["key"]: request.form.get(s["key"], "") for s in SETTINGS_SPEC}
            flash("Some settings were invalid — nothing was saved.", "danger")
            return render_template("settings/form.html", spec=SETTINGS_SPEC,
                                   values=values, errors=errors)
        flash("Settings saved. Middleware changes apply on the next poll cycle.", "success")
        return redirect(url_for("settings.index"))

    return render_template("settings/form.html", spec=SETTINGS_SPEC,
                           values=get_settings(), errors={})
