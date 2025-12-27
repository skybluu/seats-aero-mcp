"""Seats.aero MCP server built with FastMCP."""
from __future__ import annotations

import json
import os
import textwrap
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

API_BASE_URL = "https://seats.aero/partnerapi"
CHARACTER_LIMIT = 25_000
DEFAULT_TAKE = 50
TIMEOUT = httpx.Timeout(30.0, connect=10.0, read=30.0, write=30.0)
REGIONS = (
    "North America",
    "South America",
    "Africa",
    "Asia",
    "Europe",
    "Oceania",
)
CABINS = ("economy", "premium", "business", "first")


class ResponseFormat(str, Enum):
    """Supported output formats."""

    MARKDOWN = "markdown"
    JSON = "json"


class SeatsBaseModel(BaseModel):
    """Base model that enforces strict validation."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


def _split_csv(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
        return parts or None
    return value


def _validate_date(value: Optional[str]) -> Optional[str]:
    if value:
        datetime.strptime(value, "%Y-%m-%d")
    return value


class CachedSearchInput(SeatsBaseModel):
    origin_airports: List[str] = Field(
        ..., description="List of IATA origin airports such as ['JFK', 'LAX']"
    )
    destination_airports: List[str] = Field(
        ..., description="List of IATA destination airports such as ['LHR']"
    )
    start_date: Optional[str] = Field(
        None, description="Filter departures on/after this date (YYYY-MM-DD)."
    )
    end_date: Optional[str] = Field(
        None, description="Filter departures on/before this date (YYYY-MM-DD)."
    )
    cursor: Optional[int] = Field(
        None, description="Pagination cursor returned from a previous response.", ge=0
    )
    take: int = Field(
        default=DEFAULT_TAKE,
        description="Maximum number of results to retrieve (10-1000).",
        ge=10,
        le=1000,
    )
    skip: Optional[int] = Field(None, description="Number of records to skip.", ge=0)
    include_trips: bool = Field(
        default=False,
        description="Include trip-level data (increases payload size).",
    )
    minify_trips: bool = Field(
        default=False,
        description="When include_trips=true, return reduced trip fields.",
    )
    only_direct_flights: bool = Field(
        default=False, description="Return only direct itineraries when true."
    )
    carriers: Optional[List[str]] = Field(
        default=None,
        description="Limit to these carriers (e.g., ['AA','BA']).",
    )
    sources: Optional[List[str]] = Field(
        default=None,
        description="Limit to specific mileage programs (e.g., ['aeroplan']).",
    )
    cabins: Optional[List[str]] = Field(
        default=None,
        description="Require these cabins to be available (e.g., ['business']).",
    )
    include_filtered: bool = Field(
        default=False,
        description="Include dynamically-priced results normally filtered out.",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Choose 'markdown' for summaries or 'json' for full data.",
    )

    @field_validator("origin_airports", "destination_airports", mode="before")
    @classmethod
    def _coerce_airports(cls, value: Any) -> List[str]:
        parts = _split_csv(value)
        if not parts:
            raise ValueError("At least one airport is required")
        return [part.upper() for part in parts]

    @field_validator("carriers", "sources", "cabins", mode="before")
    @classmethod
    def _coerce_lists(cls, value: Any) -> Optional[List[str]]:
        result = _split_csv(value)
        if result is None:
            return None
        return result

    @field_validator("start_date", "end_date")
    @classmethod
    def _check_dates(cls, value: Optional[str]) -> Optional[str]:
        return _validate_date(value)

    @field_validator("cabins")
    @classmethod
    def _validate_cabins(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value:
            normalized = [item.lower() for item in value]
            for item in normalized:
                if item not in CABINS:
                    raise ValueError(f"Invalid cabin '{item}'.")
            return normalized
        return value


class BulkAvailabilityInput(SeatsBaseModel):
    source: str = Field(..., description="Mileage program (e.g., 'american').")
    cabin: Optional[str] = Field(
        default=None, description="Restrict to a specific cabin (economy/premium/business/first)."
    )
    start_date: Optional[str] = Field(
        None, description="Filter departures on/after this date (YYYY-MM-DD)."
    )
    end_date: Optional[str] = Field(
        None, description="Filter departures on/before this date (YYYY-MM-DD)."
    )
    origin_region: Optional[str] = Field(
        None, description="Only results originating in this region."
    )
    destination_region: Optional[str] = Field(
        None, description="Only results with this destination region."
    )
    take: int = Field(
        default=DEFAULT_TAKE, description="Page size for the API call.", ge=10, le=1000
    )
    cursor: Optional[int] = Field(None, description="Cursor from prior response.", ge=0)
    skip: int = Field(
        default=0,
        description="Number of previously retrieved rows to skip when paginating.",
        ge=0,
    )
    include_filtered: bool = Field(
        default=False,
        description="Include dynamically priced results that are otherwise filtered.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("start_date", "end_date")
    @classmethod
    def _check_dates(cls, value: Optional[str]) -> Optional[str]:
        return _validate_date(value)

    @field_validator("origin_region", "destination_region")
    @classmethod
    def _validate_region(cls, value: Optional[str]) -> Optional[str]:
        if value and value not in REGIONS:
            raise ValueError(
                f"Invalid region '{value}'. Must be one of: {', '.join(REGIONS)}."
            )
        return value

    @field_validator("cabin")
    @classmethod
    def _validate_cabin(cls, value: Optional[str]) -> Optional[str]:
        if value and value.lower() not in CABINS:
            raise ValueError("Cabin must be economy, premium, business, or first.")
        return value.lower() if value else value


class RoutesInput(SeatsBaseModel):
    source: Optional[str] = Field(
        default=None, description="Filter routes to a specific mileage program."
    )
    limit: int = Field(
        default=50,
        description="Maximum routes to summarize in markdown (JSON always returns all).",
        ge=1,
        le=200,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class TripDetailsInput(SeatsBaseModel):
    availability_id: str = Field(
        ..., description="Availability ID returned by cached search or bulk availability."
    )
    include_filtered: bool = Field(
        default=False,
        description="Include dynamically-priced trips that might be filtered out.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


mcp = FastMCP("seats_aero_mcp")


def _get_api_key() -> str:
    token = os.getenv("SEATS_AERO_PARTNER_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Set the SEATS_AERO_PARTNER_TOKEN environment variable with your partner API key."
        )
    return token


async def _call_api(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = {
        "Partner-Authorization": _get_api_key(),
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(
        base_url=API_BASE_URL,
        headers=headers,
        timeout=TIMEOUT,
    ) as client:
        response = await client.request(method, path, params=params, json=json_body)
    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text}
        message = payload.get("error") or payload.get("message") or response.text
        raise RuntimeError(f"Seats.aero API error {response.status_code}: {message}")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("Seats.aero returned invalid JSON.") from exc


def _csv(items: Optional[Sequence[str]], *, upper: bool = False, lower: bool = False) -> Optional[str]:
    if not items:
        return None
    cleaned: List[str] = []
    for item in items:
        value = item.strip()
        if not value:
            continue
        if upper:
            value = value.upper()
        if lower:
            value = value.lower()
        cleaned.append(value)
    if not cleaned:
        return None
    seen: Dict[str, None] = dict.fromkeys(cleaned)  # preserve order, remove dupes
    return ",".join(seen.keys())


def _safe_int(value: Any) -> Optional[int]:
    try:
        result = int(value)
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def _available_cabins(record: Dict[str, Any]) -> List[str]:
    mapping = {
        "Y": "economy",
        "W": "premium",
        "J": "business",
        "F": "first",
    }
    cabins: List[str] = []
    for key, label in mapping.items():
        if record.get(f"{key}Available"):
            cabins.append(label)
    return cabins


def _lowest_miles(record: Dict[str, Any]) -> Optional[int]:
    costs = [
        _safe_int(record.get("YMileageCost")),
        _safe_int(record.get("WMileageCost")),
        _safe_int(record.get("JMileageCost")),
        _safe_int(record.get("FMileageCost")),
    ]
    filtered = [value for value in costs if value is not None and value > 0]
    return min(filtered) if filtered else None


def _apply_limit(text: str) -> str:
    if len(text) <= CHARACTER_LIMIT:
        return text
    trimmed = text[: CHARACTER_LIMIT - 500]
    return (
        f"{trimmed}\n\n… Output truncated at {CHARACTER_LIMIT} characters. "
        "Narrow your filters or request JSON for pagination metadata."
    )


def _to_json(payload: Any) -> str:
    return _apply_limit(json.dumps(payload, indent=2, sort_keys=True))


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    line = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([line, separator, *body])


def _summarize_list(
    payload: Dict[str, Any],
    rows: Sequence[Sequence[str]],
    headers: Sequence[str],
    *,
    meta_lines: Sequence[str],
) -> str:
    parts = list(meta_lines)
    if rows:
        parts.append("")
        parts.append(_table(headers, rows))
    else:
        parts.append("\n_No matching records were returned._")
    return _apply_limit("\n".join(parts))


def _format_cached_search(payload: Dict[str, Any], response_format: ResponseFormat) -> str:
    if response_format is ResponseFormat.JSON:
        return _to_json(payload)
    items = payload.get("data", [])
    rows: List[List[str]] = []
    for entry in items[:50]:
        route = entry.get("Route", {})
        cabins = ", ".join(_available_cabins(entry)) or "None"
        miles = _lowest_miles(entry)
        rows.append(
            [
                entry.get("Date", "?"),
                f"{route.get('OriginAirport', '?')} → {route.get('DestinationAirport', '?')}",
                cabins,
                f"{miles:,}" if miles else "—",
                route.get("Source", "?"),
                "Yes" if entry.get("JDirect") or entry.get("FDirect") or entry.get("YDirect") else "Mixed",
            ]
        )
    summary = [
        f"**Returned** {len(items)} of {payload.get('count', '?')} records.",
        f"**Has more**: {payload.get('hasMore', False)}",
        f"**Next cursor**: {payload.get('cursor', '—')}",
    ]
    if payload.get("moreURL"):
        summary.append(f"Use `cursor={payload['cursor']}` or `skip` via {payload['moreURL']} for the next page.")
    return _summarize_list(
        payload,
        rows,
        ["Date", "Route", "Cabins", "Lowest miles", "Program", "Direct"],
        meta_lines=summary,
    )


def _format_availability(payload: Dict[str, Any], response_format: ResponseFormat) -> str:
    if response_format is ResponseFormat.JSON:
        return _to_json(payload)
    items = payload.get("data", [])
    rows: List[List[str]] = []
    for entry in items[:50]:
        route = entry.get("Route", {})
        cabins = ", ".join(_available_cabins(entry)) or "None"
        miles = _lowest_miles(entry)
        rows.append(
            [
                entry.get("Date", "?"),
                f"{route.get('OriginAirport', '?')} → {route.get('DestinationAirport', '?')}",
                cabins,
                f"{miles:,}" if miles else "—",
                entry.get("Source", route.get("Source", "?")),
                str(entry.get("YRemainingSeats", 0)),
            ]
        )
    summary = [
        f"**Returned** {len(items)} records from {payload.get('count', '?')}.",
        f"**Has more**: {payload.get('hasMore', False)}",
        f"**Next cursor**: {payload.get('cursor', '—')}",
    ]
    return _summarize_list(
        payload,
        rows,
        ["Date", "Route", "Cabins", "Lowest miles", "Program", "Y seats"],
        meta_lines=summary,
    )


def _format_routes(
    routes: List[Dict[str, Any]], response_format: ResponseFormat, limit: int
) -> str:
    if response_format is ResponseFormat.JSON:
        return _to_json(routes)
    rows: List[List[str]] = []
    for route in routes[:limit]:
        rows.append(
            [
                f"{route.get('OriginAirport', '?')} → {route.get('DestinationAirport', '?')}",
                route.get("OriginRegion", "?") + " / " + route.get("DestinationRegion", "?"),
                str(route.get("NumDaysOut", "?")),
                f"{route.get('Distance', 0):,} mi",
                route.get("Source", "?"),
            ]
        )
    summary = [f"**Total routes retrieved**: {len(routes)}"]
    return _summarize_list(
        {"count": len(routes)},
        rows,
        ["Route", "Regions", "Days Out", "Distance", "Program"],
        meta_lines=summary,
    )


def _format_trips(payload: Dict[str, Any], response_format: ResponseFormat) -> str:
    if response_format is ResponseFormat.JSON:
        return _to_json(payload)
    trips = payload.get("data", [])
    parts: List[str] = [f"**Trips returned**: {len(trips)}"]
    for idx, trip in enumerate(trips, start=1):
        segments = trip.get("AvailabilitySegments", [])
        mileage = _safe_int(trip.get("MileageCost"))
        lines = [
            f"**Trip {idx}:** {trip.get('OriginAirport')} → {trip.get('DestinationAirport')}",
            (
                f"Cabin: {trip.get('Cabin', '—')} | Mileage: {mileage:,}"
                if mileage
                else f"Cabin: {trip.get('Cabin', '—')}"
            ),
            f"Carriers: {trip.get('Carriers', '—')} | Remaining seats: {trip.get('RemainingSeats', '—')}",
        ]
        for seg in segments:
            dep = seg.get("DepartsAt")
            arr = seg.get("ArrivesAt")
            lines.append(
                f"• {seg.get('FlightNumber','?')} {seg.get('OriginAirport','?')}→{seg.get('DestinationAirport','?')} "
                f"({dep} → {arr}) {seg.get('Cabin','')}"
            )
        parts.append("\n".join(lines))
    return _apply_limit("\n\n".join(parts))


@mcp.tool(
    name="seats_cached_search",
    annotations={
        "title": "Seats.aero Cached Search",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def seats_cached_search(params: CachedSearchInput) -> str:
    """Search cached award availability between origin/destination pairs.

    Use this tool to quickly explore cached inventory exposed by the Seats.aero Partner API.
    Provide at least one origin and destination airport code. Narrow the response with
    optional dates, mileage sources, cabins, and pagination controls. Results include
    pagination metadata so you can request additional pages by passing the `cursor` or
    adjusting `skip`.
    """

    query = {
        "origin_airport": _csv(params.origin_airports, upper=True),
        "destination_airport": _csv(params.destination_airports, upper=True),
        "start_date": params.start_date,
        "end_date": params.end_date,
        "cursor": params.cursor,
        "take": params.take,
        "skip": params.skip,
        "include_trips": params.include_trips or None,
        "minify_trips": params.minify_trips or None,
        "only_direct_flights": params.only_direct_flights or None,
        "carriers": _csv(params.carriers, upper=True),
        "sources": _csv(params.sources, lower=True),
        "cabins": _csv(params.cabins, lower=True),
        "include_filtered": params.include_filtered or None,
    }
    query = {key: value for key, value in query.items() if value not in (None, "")}
    payload = await _call_api("GET", "/search", params=query)
    return _format_cached_search(payload, params.response_format)


@mcp.tool(
    name="seats_bulk_availability",
    annotations={
        "title": "Seats.aero Bulk Availability",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def seats_bulk_availability(params: BulkAvailabilityInput) -> str:
    """Retrieve high-volume availability data for a single mileage program.

    Use this when you need broad scans of a specific loyalty program. The endpoint supports
    pagination via `cursor`/`skip`, as well as filters for cabin, date range, and regions.
    This dataset can be large, so prefer tighter filters when possible.
    """

    query = {
        "source": params.source,
        "cabin": params.cabin,
        "start_date": params.start_date,
        "end_date": params.end_date,
        "origin_region": params.origin_region,
        "destination_region": params.destination_region,
        "take": params.take,
        "cursor": params.cursor,
        "skip": params.skip,
        "include_filtered": params.include_filtered or None,
    }
    query = {key: value for key, value in query.items() if value not in (None, "")}
    payload = await _call_api("GET", "/availability", params=query)
    return _format_availability(payload, params.response_format)


@mcp.tool(
    name="seats_list_routes",
    annotations={
        "title": "Seats.aero Get Routes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def seats_list_routes(params: RoutesInput) -> str:
    """List normalized routes tracked by Seats.aero, optionally filtered by mileage program."""

    query = {"source": params.source} if params.source else None
    payload = await _call_api("GET", "/routes", params=query)
    return _format_routes(payload, params.response_format, params.limit)


@mcp.tool(
    name="seats_trip_details",
    annotations={
        "title": "Seats.aero Trip Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def seats_trip_details(params: TripDetailsInput) -> str:
    """Fetch flight-level itinerary details for a cached availability record."""

    query = {"include_filtered": params.include_filtered or None}
    payload = await _call_api(
        "GET", f"/trips/{params.availability_id}", params=query
    )
    return _format_trips(payload, params.response_format)


if __name__ == "__main__":
    mcp.run()
