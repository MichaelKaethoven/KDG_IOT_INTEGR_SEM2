"""Pagination helpers for list views.

Read the `page` query arg, clamp it, and produce the (offset, last_idx) pair
PostgREST/Supabase wants for `.range(offset, last_idx)`. Templates render a
Prev/Next strip from the returned dict.
"""
from flask import request

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _parse_int(value, default: int, low: int = 1, high: int = 10**6) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < low:
        return low
    if n > high:
        return high
    return n


def parse_page(default_size: int = DEFAULT_PAGE_SIZE) -> tuple[int, int, int]:
    """Return (offset, last_idx, page_size) for the current request.

    `last_idx` is the inclusive upper bound expected by Supabase's `.range()`.
    Page size is itself capped so a hostile `?page_size=1e9` can't blow the DB.
    """
    page = _parse_int(request.args.get("page"), default=1, low=1)
    page_size = _parse_int(
        request.args.get("page_size"), default=default_size, low=1, high=MAX_PAGE_SIZE,
    )
    offset = (page - 1) * page_size
    return offset, offset + page_size - 1, page_size


def build_pagination(page_size: int, returned: int, page: int | None = None) -> dict:
    """Build the dict the templates use to render Prev/Next.

    We don't get an exact total from PostgREST without a count query, so the
    "next page" link is only shown when the current page came back full.
    """
    page = page if page is not None else _parse_int(request.args.get("page"), default=1, low=1)
    has_prev = page > 1
    has_next = returned >= page_size
    other_args = {k: v for k, v in request.args.items() if k != "page"}
    return {
        "page": page,
        "page_size": page_size,
        "has_prev": has_prev,
        "has_next": has_next,
        "prev_page": page - 1 if has_prev else None,
        "next_page": page + 1 if has_next else None,
        "args": other_args,
    }
