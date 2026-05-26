from flask import Blueprint, render_template, request, redirect, url_for
from blueprints.auth import login_required, admin_required
from db import get_db

trackers_bp = Blueprint("trackers", __name__)


@trackers_bp.route("/")
@login_required
def list_trackers():
    db = get_db()
    trackers = db.table("trackers").select("*").order("device_name").execute().data

    # Get all active assignments in one query
    active = (
        db.table("order_trackers")
        .select("tracker_id, order:orders(id, status, customer:customers(id, name))")
        .is_("removed_at", "null")
        .execute()
        .data
    )
    assignment_map = {a["tracker_id"]: a["order"] for a in active}

    # One round-trip: pull all rows for these device_names ordered by time desc,
    # then keep the latest per device_name in Python.
    device_names = [t["device_name"] for t in trackers]
    last_seen: dict = {}
    if device_names:
        locs = (
            db.table("device_locations")
            .select("device_name, time")
            .in_("device_name", device_names)
            .order("time", desc=True)
            .execute()
            .data
        )
        for row in locs:
            name = row["device_name"]
            if name not in last_seen:
                last_seen[name] = row["time"]

    for tracker in trackers:
        tracker["assignment"] = assignment_map.get(tracker["id"])
        tracker["last_seen"] = last_seen.get(tracker["device_name"])

    return render_template("trackers/list.html", trackers=trackers)


@trackers_bp.route("/new", methods=["GET", "POST"])
@admin_required
def new_tracker():
    if request.method == "POST":
        db = get_db()
        db.table("trackers").insert({
            "device_name": request.form["device_name"],
            "serial_number": request.form.get("serial_number") or None,
            "notes": request.form.get("notes") or None,
        }).execute()
        return redirect(url_for("trackers.list_trackers"))
    return render_template("trackers/form.html", tracker=None)


@trackers_bp.route("/<tracker_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_tracker(tracker_id):
    db = get_db()
    tracker = db.table("trackers").select("*").eq("id", tracker_id).single().execute().data
    if request.method == "POST":
        db.table("trackers").update({
            "device_name": request.form["device_name"],
            "serial_number": request.form.get("serial_number") or None,
            "notes": request.form.get("notes") or None,
        }).eq("id", tracker_id).execute()
        return redirect(url_for("trackers.list_trackers"))
    return render_template("trackers/form.html", tracker=tracker)


@trackers_bp.route("/<tracker_id>/delete", methods=["POST"])
@admin_required
def delete_tracker(tracker_id):
    db = get_db()
    db.table("trackers").delete().eq("id", tracker_id).execute()
    return redirect(url_for("trackers.list_trackers"))
