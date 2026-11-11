"""Challenge 1 — live fare lookup and net effective cost.

Net effective cost (NEC) treats miles as a cash-equivalent offset:

    NEC = F_base + sum(A_fees) - (M_earned * V_cpp)

`F_base` is the itinerary fare. `A_fees` are ancillary charges that the
traveler's loyalty tier does not already waive (checked bags, seat selection).
`M_earned` is miles credited on the base fare. `V_cpp` is the currency value
of one mile, converted from cents-per-point.

`loyalty_rules.json` is expected in the project root. The loader accepts
either a list of tiers or a name-keyed object, and several common field
aliases, so a generated rules file can drop in without a rewrite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

from utils.app_secrets import get_secret

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"

# Pre-defined North America <-> South America city pairs.
ROUTES: list[dict[str, str]] = [
    {"label": "Bogota (BOG) → Miami (MIA)", "departure_id": "BOG", "arrival_id": "MIA"},
    {"label": "Sao Paulo (GRU) → New York (JFK)", "departure_id": "GRU", "arrival_id": "JFK"},
    {"label": "Buenos Aires (EZE) → Miami (MIA)", "departure_id": "EZE", "arrival_id": "MIA"},
    {"label": "Lima (LIM) → Miami (MIA)", "departure_id": "LIM", "arrival_id": "MIA"},
    {"label": "Santiago (SCL) → New York (JFK)", "departure_id": "SCL", "arrival_id": "JFK"},
]

# Illustrative fares used only when SerpApi is not configured or the call fails.
# They let the NEC comparison render during local review.
SAMPLE_OFFERS: dict[tuple[str, str], dict[str, Any]] = {
    ("BOG", "MIA"): {"price": 286.0, "airline": "Avianca", "stops": 0},
    ("GRU", "JFK"): {"price": 548.0, "airline": "LATAM", "stops": 0},
    ("EZE", "MIA"): {"price": 612.0, "airline": "American", "stops": 1},
    ("LIM", "MIA"): {"price": 394.0, "airline": "LATAM", "stops": 0},
    ("SCL", "JFK"): {"price": 705.0, "airline": "Delta", "stops": 1},
}

_BAG_FEE_KEYS = (
    "checked_bag_fee",
    "baggage_fee",
    "bag_fee",
    "checked_baggage_fee",
    "checked_bag_usd",
    "first_bag_fee",
)
_SEAT_FEE_KEYS = (
    "seat_selection_fee",
    "seat_fee",
    "seat_selection_usd",
    "advance_seat_fee",
)
_BAGS_WAIVED_KEYS = (
    "checked_bags_waived",
    "bags_waived",
    "free_checked_bags",
    "included_checked_bags",
    "baggage_allowance",
    "checked_bags_included",
    "free_bags",
)
_MILES_KEYS = (
    "miles_per_currency_unit",
    "miles_per_dollar",
    "miles_earned_per_dollar",
    "earn_rate",
    "miles_per_usd",
)
_CPP_KEYS = (
    "value_per_point_cents",
    "cents_per_point",
    "cpp",
    "value_cpp",
    "point_value_cents",
)


@dataclass
class TierRule:
    """Normalized loyalty tier used by the NEC calculation."""

    name: str
    checked_bags_waived: int
    seat_fee_waived: bool
    miles_per_currency_unit: float
    value_per_point_cents: float


@dataclass
class LoyaltyProgram:
    """Fee schedule plus the tiers loaded from `loyalty_rules.json`."""

    currency: str
    checked_bag_fee: float
    seat_selection_fee: float
    tiers: list[TierRule]
    source: str
    assumptions: list[str] = field(default_factory=list)


@dataclass
class CostBreakdown:
    """One row of the comparison: a fare priced for a single tier."""

    route: str
    airline: str
    tier: str
    base_fare: float
    ancillary_fees: float
    miles_earned: float
    point_value: float
    net_effective_cost: float
    price_source: str
    stops: int | None = None


def load_loyalty_rules(path: Path) -> LoyaltyProgram:
    """Load and normalize `loyalty_rules.json`.

    Raises FileNotFoundError when the file has not been added yet, and
    ValueError when the JSON has no usable tier definitions.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Loyalty rules file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("loyalty_rules.json must be a JSON object.")

    assumptions: list[str] = []
    currency = str(payload.get("currency") or payload.get("currency_code") or "USD")
    program_cpp = _first_number(payload, _CPP_KEYS)

    checked_bag_fee = _find_fee(payload, _BAG_FEE_KEYS, bag=True)
    seat_selection_fee = _find_fee(payload, _SEAT_FEE_KEYS, bag=False)
    if checked_bag_fee is None:
        checked_bag_fee = 35.0
        assumptions.append("Checked-bag fee defaulted to 35 because the rules file did not set one.")
    if seat_selection_fee is None:
        seat_selection_fee = 0.0
        assumptions.append("Seat-selection fee defaulted to 0 because the rules file did not set one.")

    tiers = _normalize_tiers(payload.get("tiers") or payload.get("loyalty_tiers"), program_cpp)
    if not tiers:
        raise ValueError(
            "No tiers found. Expected a 'tiers' list or object with per-tier baggage and mileage fields."
        )

    return LoyaltyProgram(
        currency=currency,
        checked_bag_fee=checked_bag_fee,
        seat_selection_fee=seat_selection_fee,
        tiers=tiers,
        source=str(path),
        assumptions=assumptions,
    )


def default_loyalty_program() -> LoyaltyProgram:
    """Built-in schedule used until `loyalty_rules.json` is added."""
    return LoyaltyProgram(
        currency="USD",
        checked_bag_fee=35.0,
        seat_selection_fee=18.0,
        tiers=[
            TierRule("Member", 0, False, 5.0, 1.0),
            TierRule("Silver", 1, False, 7.0, 1.2),
            TierRule("Gold", 2, True, 9.0, 1.5),
        ],
        source="built-in defaults",
        assumptions=[
            "Using built-in tiers until loyalty_rules.json is placed in the project root."
        ],
    )


def net_effective_cost(
    base_fare: float,
    tier: TierRule,
    program: LoyaltyProgram,
    checked_bags: int,
    include_seat_fee: bool,
) -> tuple[float, float, float, float]:
    """Return ancillary fees, miles earned, point value, and NEC.

    Baggage fees apply only to bags beyond the tier waiver. A waived seat
    fee drops that ancillary to zero even when the traveler requests a seat.
    Point value converts cents-per-point into the same currency as the fare:

        V_cpp = cents_per_point / 100
        NEC = F_base + sum(A_fees) - (M_earned * V_cpp)
    """
    chargeable_bags = max(int(checked_bags) - int(tier.checked_bags_waived), 0)
    bag_fees = program.checked_bag_fee * chargeable_bags
    if include_seat_fee and not tier.seat_fee_waived:
        seat_fee = program.seat_selection_fee
    else:
        seat_fee = 0.0

    ancillary = bag_fees + seat_fee
    miles_earned = max(base_fare, 0.0) * tier.miles_per_currency_unit
    value_per_point = tier.value_per_point_cents / 100.0
    point_value = miles_earned * value_per_point
    nec = base_fare + ancillary - point_value
    return ancillary, miles_earned, point_value, nec


def fetch_flight_offer(
    departure_id: str,
    arrival_id: str,
    outbound_date: date,
    return_date: date | None = None,
    currency: str = "USD",
    api_key: str | None = None,
) -> dict[str, Any]:
    """Fetch the cheapest Google Flights offer for one city pair.

    Uses the `serpapi` client when that package is installed, and falls
    back to the SerpApi REST endpoint through `requests`.
    """
    key = (api_key if api_key is not None else get_secret("SERPAPI_API_KEY")).strip()
    if not key or key.startswith("your_"):
        raise RuntimeError("SERPAPI_API_KEY is not configured in Streamlit secrets.")

    params: dict[str, Any] = {
        "engine": "google_flights",
        "departure_id": departure_id,
        "arrival_id": arrival_id,
        "outbound_date": outbound_date.isoformat(),
        "currency": currency,
        "hl": "en",
        "type": "1" if return_date else "2",
        "api_key": key,
    }
    if return_date:
        params["return_date"] = return_date.isoformat()

    payload = _serpapi_search(params)
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))

    offer = _cheapest_offer(payload)
    if offer is None:
        raise RuntimeError(
            f"SerpApi returned no priced itineraries for {departure_id} → {arrival_id}."
        )
    offer["price_source"] = "serpapi"
    return offer


def build_comparison(
    offers: list[dict[str, Any]],
    program: LoyaltyProgram,
    tiers: list[TierRule],
    checked_bags: int,
    include_seat_fee: bool,
) -> pd.DataFrame:
    """Price every selected offer under every selected tier."""
    rows: list[dict[str, Any]] = []
    for offer in offers:
        for tier in tiers:
            ancillary, miles, point_value, nec = net_effective_cost(
                base_fare=float(offer["price"]),
                tier=tier,
                program=program,
                checked_bags=checked_bags,
                include_seat_fee=include_seat_fee,
            )
            rows.append(
                {
                    "Route": offer["route"],
                    "Airline": offer.get("airline") or "—",
                    "Stops": offer.get("stops"),
                    "Tier": tier.name,
                    "Base fare": round(float(offer["price"]), 2),
                    "Ancillary fees": round(ancillary, 2),
                    "Miles earned": round(miles, 1),
                    "Point value": round(point_value, 2),
                    "Net effective cost": round(nec, 2),
                    "Price source": offer.get("price_source", ""),
                }
            )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    # Mark the lowest NEC on each route so the comparison is easy to scan.
    best_index = frame.groupby("Route")["Net effective cost"].idxmin()
    frame["Best on route"] = False
    frame.loc[best_index, "Best on route"] = True
    return frame.sort_values(["Route", "Net effective cost"]).reset_index(drop=True)


def render_travel_optimizer(root: Path) -> None:
    """Sidebar-independent Challenge 1 workspace."""
    rules_path = root / "loyalty_rules.json"
    try:
        program = load_loyalty_rules(rules_path)
    except FileNotFoundError:
        program = default_loyalty_program()
        st.info(
            "Place `loyalty_rules.json` in the project root to replace the built-in "
            "Member / Silver / Gold fee schedule."
        )
    except (json.JSONDecodeError, ValueError) as exc:
        st.error(f"Could not read loyalty rules: {exc}")
        return

    for note in program.assumptions:
        st.warning(note)

    with st.expander("How net effective cost is calculated", expanded=False):
        st.markdown(
            r"""
`NEC = F_base + Σ(A_fees) − (M_earned × V_cpp)`

- **F_base** — itinerary fare from SerpApi (or a labeled sample fare).
- **A_fees** — checked-bag and seat fees still owed after the loyalty waiver.
- **M_earned** — base fare × the tier's miles per currency unit.
- **V_cpp** — cents-per-point ÷ 100, so miles are subtracted in fare currency.
            """
        )
        st.caption(
            f"Bag fee {program.checked_bag_fee:.2f} {program.currency} · "
            f"Seat fee {program.seat_selection_fee:.2f} {program.currency} · "
            f"Rules: {program.source}"
        )

    route_labels = [route["label"] for route in ROUTES]
    default_labels = route_labels[:2]

    col_routes, col_dates = st.columns([1.3, 1])
    with col_routes:
        selected_labels = st.multiselect(
            "Routes",
            route_labels,
            default=default_labels,
            help="Pre-defined city pairs between South America and the United States.",
        )
    with col_dates:
        outbound = st.date_input("Outbound", value=date.today() + timedelta(days=30))
        round_trip = st.checkbox("Round trip", value=False)
        return_on = None
        if round_trip:
            return_on = st.date_input("Return", value=date.today() + timedelta(days=37))

    tier_names = [tier.name for tier in program.tiers]
    col_tier, col_bags, col_seat = st.columns(3)
    with col_tier:
        tier_choice = st.selectbox(
            "Loyalty tier",
            ["Compare all tiers", *tier_names],
            help="Compare all tiers to rank the same fare by net effective cost.",
        )
    with col_bags:
        checked_bags = st.number_input("Checked bags", min_value=0, max_value=4, value=1, step=1)
    with col_seat:
        include_seat = st.checkbox("Include seat-selection fee", value=True)

    selected_tiers = program.tiers if tier_choice == "Compare all tiers" else [
        tier for tier in program.tiers if tier.name == tier_choice
    ]
    selected_routes = [route for route in ROUTES if route["label"] in selected_labels]

    if st.button("Search flights and compare NEC", type="primary", disabled=not selected_routes):
        offers, errors = _collect_offers(
            selected_routes,
            outbound=outbound,
            return_date=return_on,
            currency=program.currency,
        )
        for message in errors:
            st.warning(message)
        if not offers:
            st.error("No fares were available to price.")
            return

        comparison = build_comparison(
            offers,
            program,
            selected_tiers,
            checked_bags=int(checked_bags),
            include_seat_fee=include_seat,
        )
        st.session_state["nec_comparison"] = comparison
        st.session_state["nec_currency"] = program.currency

    comparison = st.session_state.get("nec_comparison")
    if isinstance(comparison, pd.DataFrame) and not comparison.empty:
        currency = st.session_state.get("nec_currency", program.currency)
        st.subheader("Net effective cost comparison")
        st.caption("The highlighted row is the lowest net effective cost for each route.")
        st.dataframe(
            _style_comparison(comparison),
            width="stretch",
            hide_index=True,
            column_config={
                "Base fare": st.column_config.NumberColumn(format=f"%.2f {currency}"),
                "Ancillary fees": st.column_config.NumberColumn(format=f"%.2f {currency}"),
                "Point value": st.column_config.NumberColumn(format=f"%.2f {currency}"),
                "Net effective cost": st.column_config.NumberColumn(format=f"%.2f {currency}"),
                "Best on route": st.column_config.CheckboxColumn("Best on route"),
            },
        )
        best = comparison.loc[comparison["Best on route"]]
        if not best.empty:
            winner = best.sort_values("Net effective cost").iloc[0]
            st.success(
                f"Lowest NEC in this search: {winner['Route']} on {winner['Tier']} "
                f"at {winner['Net effective cost']:.2f} {currency}."
            )


def _collect_offers(
    routes: list[dict[str, str]],
    outbound: date,
    return_date: date | None,
    currency: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch live offers, substituting a labeled sample fare when a route fails."""
    offers: list[dict[str, Any]] = []
    errors: list[str] = []
    key = get_secret("SERPAPI_API_KEY")
    live = bool(key) and not key.startswith("your_")

    if not live:
        errors.append(
            "SERPAPI_API_KEY is not set in Streamlit secrets. "
            "Showing labeled sample fares so the NEC table still runs."
        )

    for route in routes:
        pair = (route["departure_id"], route["arrival_id"])
        offer: dict[str, Any] | None = None
        if live:
            try:
                offer = fetch_flight_offer(
                    route["departure_id"],
                    route["arrival_id"],
                    outbound,
                    return_date=return_date,
                    currency=currency,
                    api_key=key,
                )
            except (RuntimeError, requests.RequestException, ValueError) as exc:
                errors.append(f"{route['label']}: live search failed ({exc}). Using a sample fare.")

        if offer is None:
            sample = SAMPLE_OFFERS.get(pair)
            if sample is None:
                errors.append(f"{route['label']}: no sample fare is defined for this route.")
                continue
            offer = {
                "price": sample["price"],
                "airline": sample["airline"],
                "stops": sample["stops"],
                "price_source": "sample",
            }
        offer["route"] = route["label"]
        offers.append(offer)
    return offers, errors


def _serpapi_search(params: dict[str, Any]) -> dict[str, Any]:
    """Call SerpApi via the official client, then via HTTP if that import fails."""
    search_params = {key: value for key, value in params.items() if key != "api_key"}
    try:
        import serpapi
    except ImportError:
        serpapi = None

    if serpapi is not None and hasattr(serpapi, "Client"):
        client = serpapi.Client(api_key=params["api_key"])
        result = client.search(search_params)
        return _as_result_dict(result)

    try:
        from serpapi import GoogleSearch
    except ImportError:
        GoogleSearch = None  # type: ignore[misc, assignment]

    if GoogleSearch is not None:
        return _as_result_dict(GoogleSearch(params).get_dict())

    response = requests.get(SERPAPI_ENDPOINT, params=params, timeout=45)
    response.raise_for_status()
    return _as_result_dict(response.json())


def _as_result_dict(result: Any) -> dict[str, Any]:
    """Normalize SerpApi client objects and raw JSON into a dictionary."""
    if isinstance(result, dict):
        return result
    if hasattr(result, "as_dict"):
        converted = result.as_dict()
        if isinstance(converted, dict):
            return converted
    if hasattr(result, "data") and isinstance(result.data, dict):
        return result.data
    raise RuntimeError("Unexpected SerpApi response.")


def _cheapest_offer(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the lowest priced itinerary from best_flights and other_flights."""
    groups: list[dict[str, Any]] = []
    for key in ("best_flights", "other_flights"):
        bucket = payload.get(key) or []
        if isinstance(bucket, list):
            groups.extend(item for item in bucket if isinstance(item, dict))

    priced: list[tuple[float, dict[str, Any]]] = []
    for group in groups:
        price = _price_amount(group.get("price"))
        if price is None:
            continue
        priced.append((price, group))
    if not priced:
        return None

    price, group = min(priced, key=lambda item: item[0])
    legs = group.get("flights") or []
    first = legs[0] if isinstance(legs, list) and legs else {}
    airline = first.get("airline") if isinstance(first, dict) else None
    stops = max(len(legs) - 1, 0) if isinstance(legs, list) else None
    return {"price": price, "airline": airline, "stops": stops}


def _price_amount(price: Any) -> float | None:
    if isinstance(price, (int, float)):
        return float(price)
    if isinstance(price, str):
        cleaned = "".join(ch for ch in price if ch.isdigit() or ch == ".")
        return float(cleaned) if cleaned else None
    if isinstance(price, dict):
        for key in ("amount", "total", "price", "extracted_price"):
            if key in price:
                return _price_amount(price[key])
    return None


def _style_comparison(frame: pd.DataFrame):
    """Apply theme-independent row colors and highlight the winning NEC."""
    def _paint(row: pd.Series) -> list[str]:
        style = "background-color: #f1f5f9; color: #1e293b"
        if bool(row.get("Best on route")):
            style = "background-color: #d1fae5; color: #12372a; font-weight: 600"
        return [style] * len(row)

    return frame.style.apply(_paint, axis=1).format(
        {
            "Base fare": "{:.2f}",
            "Ancillary fees": "{:.2f}",
            "Miles earned": "{:.1f}",
            "Point value": "{:.2f}",
            "Net effective cost": "{:.2f}",
        }
    )


def _normalize_tiers(raw_tiers: Any, program_cpp: float | None) -> list[TierRule]:
    if isinstance(raw_tiers, dict):
        items = [(str(name), value) for name, value in raw_tiers.items()]
    elif isinstance(raw_tiers, list):
        items = []
        for entry in raw_tiers:
            if isinstance(entry, dict):
                name = str(entry.get("name") or entry.get("tier") or entry.get("id") or "Tier")
                items.append((name, entry))
    else:
        return []

    tiers: list[TierRule] = []
    for name, entry in items:
        if not isinstance(entry, dict):
            continue
        bags = _first_int(entry, _BAGS_WAIVED_KEYS)
        if bags is None:
            waived_flag = _first_bool(
                entry,
                ("baggage_fee_waived", "bags_waived_flag", "free_checked_bag", "baggage_included"),
            )
            bags = 1 if waived_flag else 0
        seat_waived = bool(
            _first_bool(
                entry,
                ("seat_fee_waived", "seat_selection_waived", "free_seat_selection", "waive_seat_fee"),
            )
        )
        miles = _first_number(entry, _MILES_KEYS)
        if miles is None:
            multiplier = _first_number(entry, ("miles_multiplier", "earn_multiplier", "multiplier"))
            base = _first_number(entry, ("base_miles_per_currency_unit", "base_miles_per_dollar"))
            if multiplier is not None:
                miles = (base if base is not None else 5.0) * multiplier
            else:
                miles = 5.0
        cpp = _first_number(entry, _CPP_KEYS)
        if cpp is None:
            cpp = program_cpp if program_cpp is not None else 1.0
        tiers.append(
            TierRule(
                name=name,
                checked_bags_waived=max(bags, 0),
                seat_fee_waived=seat_waived,
                miles_per_currency_unit=miles,
                value_per_point_cents=cpp,
            )
        )
    return tiers


def _find_fee(payload: dict[str, Any], keys: tuple[str, ...], bag: bool) -> float | None:
    """Look for a fee on the root object or under a nested fees schedule."""
    direct = _first_number(payload, keys)
    if direct is not None:
        return direct

    for container_key in ("fees", "ancillary_fees", "fee_schedule", "ancillaries"):
        container = payload.get(container_key)
        if isinstance(container, dict):
            found = _first_number(container, keys)
            if found is not None:
                return found
            # Nested one more level: {"checked_bag": {"amount": 35}}
            for value in container.values():
                if isinstance(value, dict) and _looks_like_target_fee(value, bag):
                    amount = _first_number(value, ("amount", "fee", "price", "usd", "value"))
                    if amount is not None:
                        return amount
        elif isinstance(container, list):
            for item in container:
                if isinstance(item, dict) and _looks_like_target_fee(item, bag):
                    amount = _first_number(item, ("amount", "fee", "price", "usd", "value"))
                    if amount is not None:
                        return amount
    return None


def _looks_like_target_fee(item: dict[str, Any], bag: bool) -> bool:
    label = " ".join(
        str(item.get(key, ""))
        for key in ("code", "id", "name", "type", "label")
    ).lower()
    if bag:
        return any(token in label for token in ("bag", "baggage", "luggage"))
    return "seat" in label


def _first_number(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    lowered = {str(key).lower(): value for key, value in data.items()}
    for key in keys:
        if key.lower() not in lowered:
            continue
        number = _as_float(lowered[key.lower()])
        if number is not None:
            return number
    return None


def _first_int(data: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    number = _first_number(data, keys)
    if number is None:
        return None
    return int(number)


def _first_bool(data: dict[str, Any], keys: tuple[str, ...]) -> bool:
    lowered = {str(key).lower(): value for key, value in data.items()}
    for key in keys:
        if key.lower() in lowered:
            return _as_bool(lowered[key.lower()])
    return False


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    if isinstance(value, dict):
        return _first_number(value, ("amount", "value", "usd", "fee", "price"))
    return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "waived"}
    return False
