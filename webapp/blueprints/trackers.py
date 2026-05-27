import os

import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash
from blueprints.auth import login_required, admin_required, current_customer_id
from db import get_db

trackers_bp = Blueprint("trackers", __name__)

MIDDLEWARE_URL = os.environ.get("MIDDLEWARE_URL", "http://middleware:5500")


@trackers_bp.route("/")
@login_required
def list_trackers():
    db = get_db()
    scope_id = current_customer_id()

    # Get all active assignments in one query, joined with order+customer.
    active = (
        db.table("order_trackers")
        .select("tracker_id, order:orders(id, status, customer:customers(id, name))")
        .is_("removed_at", "null")
        .execute()
        .data
    )
    if scope_id:
        active = [a for a in active if a["order"] and a["order"]["customer"]
                  and a["order"]["customer"]["id"] == scope_id]
    assignment_map = {a["tracker_id"]: a["order"] for a in active}

    if scope_id:
        # Customer sees only trackers currently assigned to one of their orders.
        scoped_ids = list(assignment_map.keys())
        if scoped_ids:
            trackers = (
                db.table("trackers")
                .select("*")
                .in_("id", scoped_ids)
                .order("device_name")
                .execute()
                .data
            )
        else:
            trackers = []
    else:
        trackers = db.table("trackers").select("*").order("device_name").execute().data

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


@trackers_bp.route("/sync", methods=["POST"])
@admin_required
def sync_trackers():
    try:
        resp = requests.get(f"{MIDDLEWARE_URL}/devicelist", timeout=60)
        resp.raise_for_status()
        devices = resp.json().get("devices", [])
    except requests.RequestException as e:
        flash(f"Could not reach middleware at {MIDDLEWARE_URL}: {e}", "danger")
        return redirect(url_for("trackers.list_trackers"))
    except ValueError:
        flash("Middleware returned an invalid response.", "danger")
        return redirect(url_for("trackers.list_trackers"))

    db = get_db()
    existing = db.table("trackers").select("id, device_name, serial_number").execute().data
    # Google's canonic_id is what we store as serial_number. Match by that first;
    # fall back to device_name for legacy rows added before sync existed so we
    # adopt them in place instead of creating duplicates.
    by_serial = {t["serial_number"]: t for t in existing if t.get("serial_number")}
    by_name_legacy = {t["device_name"]: t for t in existing if not t.get("serial_number")}

    added, updated, unchanged = 0, 0, 0
    for dev in devices:
        name = dev.get("device_name")
        serial = dev.get("canonic_id")
        if not name or not serial:
            continue
        row = by_serial.get(serial) or by_name_legacy.pop(name, None)
        if row is None:
            db.table("trackers").insert({
                "device_name": name,
                "serial_number": serial,
            }).execute()
            added += 1
        elif row.get("device_name") != name or row.get("serial_number") != serial:
            db.table("trackers").update({
                "device_name": name,
                "serial_number": serial,
            }).eq("id", row["id"]).execute()
            updated += 1
        else:
            unchanged += 1

    flash(
        f"Sync complete: {added} added, {updated} updated, {unchanged} already current.",
        "success",
    )
    return redirect(url_for("trackers.list_trackers"))
