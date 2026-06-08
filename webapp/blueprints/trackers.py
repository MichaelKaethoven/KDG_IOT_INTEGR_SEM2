import os
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash
from blueprints.auth import login_required, admin_required, current_customer_id
from db import get_db
from settings_store import get_setting
from pagination import parse_page, build_pagination

_TRACKER_COLS = "id, device_name, serial_number, notes, created_at"

trackers_bp = Blueprint("trackers", __name__)

MIDDLEWARE_URL = os.environ.get("MIDDLEWARE_URL", "http://middleware:5500")
DEVICE_API_TOKEN = os.environ.get("DEVICE_API_TOKEN", "")


def _is_stale(last_seen_iso, cutoff) -> bool:
    """True if the tracker has no ping at all, or its last ping is before cutoff."""
    if not last_seen_iso:
        return True
    try:
        ts = datetime.fromisoformat(last_seen_iso.replace("Z", "+00:00"))
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts < cutoff


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

    offset, last_idx, page_size = parse_page()
    if scope_id:
        # Customer sees only trackers currently assigned to one of their orders.
        scoped_ids = list(assignment_map.keys())
        if scoped_ids:
            trackers = (
                db.table("trackers")
                .select(_TRACKER_COLS)
                .in_("id", scoped_ids)
                .order("device_name")
                .range(offset, last_idx)
                .execute()
                .data
            )
        else:
            trackers = []
    else:
        trackers = (
            db.table("trackers")
            .select(_TRACKER_COLS)
            .order("device_name")
            .range(offset, last_idx)
            .execute()
            .data
        )

    # One row per device via the latest_device_locations view (DISTINCT ON in
    # SQL). Avoids dragging the full device_locations history through the wire
    # just to keep the newest per device. See db/migrations/006.
    device_names = [t["device_name"] for t in trackers]
    last_seen: dict = {}
    if device_names:
        locs = (
            db.table("latest_device_locations")
            .select("device_name, time")
            .in_("device_name", device_names)
            .execute()
            .data
        )
        for row in locs:
            last_seen[row["device_name"]] = row["time"]

    stale_hours = get_setting("tracker_stale_hours")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
    for tracker in trackers:
        tracker["assignment"] = assignment_map.get(tracker["id"])
        tracker["last_seen"] = last_seen.get(tracker["device_name"])
        tracker["stale"] = _is_stale(tracker["last_seen"], cutoff)

    stale_count = sum(1 for t in trackers if t["stale"])

    # ?filter=stale shows only trackers with no ping in the last stale_hours.
    show_stale_only = request.args.get("filter") == "stale"
    if show_stale_only:
        trackers = [t for t in trackers if t["stale"]]

    return render_template(
        "trackers/list.html",
        trackers=trackers,
        stale_hours=stale_hours,
        stale_count=stale_count,
        show_stale_only=show_stale_only,
        pagination=build_pagination(page_size, len(trackers)),
    )


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
        # device_name is intentionally not editable here: it is synced from
        # Google Find Hub (matched on serial_number/canonic_id) and is the join
        # key for location data. Rename in Find Hub + "Sync from Google" instead.
        db.table("trackers").update({
            "serial_number": request.form.get("serial_number") or None,
            "notes": request.form.get("notes") or None,
        }).eq("id", tracker_id).execute()
        return redirect(url_for("trackers.list_trackers"))
    notes = (
        db.table("tracker_notes")
        .select("*")
        .eq("tracker_id", tracker_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )
    return render_template("trackers/form.html", tracker=tracker, notes=notes)


@trackers_bp.route("/<tracker_id>/notes", methods=["POST"])
@admin_required
def add_tracker_note(tracker_id):
    note = (request.form.get("note") or "").strip()
    if not note:
        flash("Note cannot be empty.", "warning")
        return redirect(url_for("trackers.edit_tracker", tracker_id=tracker_id))
    db = get_db()
    db.table("tracker_notes").insert({
        "tracker_id": tracker_id,
        "note": note,
    }).execute()
    flash("Note added.", "success")
    return redirect(url_for("trackers.edit_tracker", tracker_id=tracker_id))


@trackers_bp.route("/<tracker_id>/delete", methods=["POST"])
@admin_required
def delete_tracker(tracker_id):
    db = get_db()
    active = (
        db.table("order_trackers")
        .select("order_id")
        .eq("tracker_id", tracker_id)
        .is_("removed_at", "null")
        .limit(1)
        .execute()
        .data
    )
    if active:
        flash("Cannot delete a tracker that is assigned to an active order. "
              "Remove it from the order first.", "danger")
        return redirect(url_for("trackers.list_trackers"))
    db.table("trackers").delete().eq("id", tracker_id).execute()
    return redirect(url_for("trackers.list_trackers"))


@trackers_bp.route("/sync", methods=["POST"])
@admin_required
def sync_trackers():
    headers = {"X-Device-Token": DEVICE_API_TOKEN} if DEVICE_API_TOKEN else {}
    try:
        resp = requests.get(f"{MIDDLEWARE_URL}/devicelist", timeout=60, headers=headers)
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
