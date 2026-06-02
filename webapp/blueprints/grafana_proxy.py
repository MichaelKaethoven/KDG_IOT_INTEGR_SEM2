import os

import requests
from flask import Blueprint, request, Response
from urllib.parse import urlencode

from blueprints.auth import login_required, current_customer_id

grafana_bp = Blueprint("grafana", __name__)

# Internal address of Grafana on the private network. Grafana is NOT publicly
# reachable; this proxy (gated by login_required) is the only way in, so the
# portal session is the access boundary. Grafana itself runs anonymous Viewer.
GRAFANA_INTERNAL_URL = os.environ.get("GRAFANA_INTERNAL_URL", "http://grafana:3000").rstrip("/")

# Hop-by-hop headers must not be forwarded (RFC 7230 §6.1).
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
}
_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]


@grafana_bp.route("/grafana", defaults={"subpath": ""}, methods=_METHODS)
@grafana_bp.route("/grafana/", defaults={"subpath": ""}, methods=_METHODS)
@grafana_bp.route("/grafana/<path:subpath>", methods=_METHODS)
@login_required
def proxy(subpath: str):
    # Forward query params, but pin var-customer to the session's customer for
    # customer-scoped logins so they cannot view another customer's data by
    # editing the iframe URL. (Deeper per-query isolation needs Postgres RLS —
    # tracked as a follow-up; this closes the navigation-level leak.)
    args = [(k, v) for k, v in request.args.items(multi=True)]
    scope_id = current_customer_id()
    if scope_id:
        args = [(k, v) for (k, v) in args if k != "var-customer"]
        args.append(("var-customer", scope_id))
    query = urlencode(args)

    # Grafana runs with GF_SERVER_SERVE_FROM_SUB_PATH=true, so it registers every
    # route under /grafana/ and expects the prefix to survive the proxy hop. If we
    # forwarded the bare subpath, Grafana would 302 back to /grafana/... and the
    # browser would loop (ERR_TOO_MANY_REDIRECTS). Keep the prefix intact.
    target = f"{GRAFANA_INTERNAL_URL}/grafana/{subpath}"
    if query:
        target = f"{target}?{query}"

    fwd_headers = {k: v for k, v in request.headers if k.lower() not in _HOP_BY_HOP}
    # Avoid compressed responses so we can stream raw bytes back unchanged.
    fwd_headers["Accept-Encoding"] = "identity"

    upstream = requests.request(
        method=request.method,
        url=target,
        headers=fwd_headers,
        data=request.get_data(),
        cookies=request.cookies,
        allow_redirects=False,
        stream=True,
        timeout=30,
    )

    excluded = _HOP_BY_HOP | {"content-encoding", "content-length"}
    headers = [(k, v) for k, v in upstream.headers.items() if k.lower() not in excluded]

    return Response(
        upstream.iter_content(chunk_size=8192),
        status=upstream.status_code,
        headers=headers,
    )
