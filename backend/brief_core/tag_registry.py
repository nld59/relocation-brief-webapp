"""Tag registry.

Single source of truth for *what a tag means* and how it is derived from
microhood-level metrics.

Design goals:
1) Deterministic and explainable (no LLM involvement).
2) Scalable to new cities (as long as they expose the same metric keys).
3) Every tag can influence microhood ranking (even if via a proxy).

Notes
-----
The Brussels city-pack currently exposes these microhood metrics:
  cafes_density, restaurants_density, bars_density, parks_share, parks_km2,
  schools_density, childcare_density, metro_density, tram_density, train_density,
  area_km2

If a new city adds more metrics (e.g., price_index, crime_index), you can extend
signals here without changing the ranking engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional


Scope = Literal["commune", "microhood", "both"]
Direction = Literal["high", "low"]


@dataclass(frozen=True)
class Signal:
    """A measurable proxy.

    metric: key inside microhood.metrics
    direction: "high" means higher is better; "low" means lower is better
    weight: relative importance within this tag
    """

    metric: str
    direction: Direction = "high"
    weight: float = 1.0


@dataclass(frozen=True)
class TagDef:
    id: str
    scope: Scope
    description: str
    # A tag can be derived from one or more signals.
    signals: List[Signal]
    # Optional textual hints used in debug.
    notes: Optional[str] = None


def _s(metric: str, direction: Direction = "high", weight: float = 1.0) -> Signal:
    return Signal(metric=metric, direction=direction, weight=weight)


# Registry. Keep ids aligned with UI / city-pack tag ids.
TAG_REGISTRY: Dict[str, TagDef] = {
    # Lifestyle
    "cafes_brunch": TagDef(
        id="cafes_brunch",
        scope="both",
        description="Many cafes and brunch places nearby.",
        signals=[_s("cafes_density", "high", 1.0)],
    ),
    "restaurants": TagDef(
        id="restaurants",
        scope="both",
        description="Strong restaurant scene (variety + density).",
        signals=[_s("restaurants_density", "high", 1.0)],
    ),
    "nightlife": TagDef(
        id="nightlife",
        scope="both",
        description="Bars and evening activity.",
        signals=[_s("bars_density", "high", 0.8), _s("restaurants_density", "high", 0.2)],
    ),
    "culture_museums": TagDef(
        id="culture_museums",
        scope="both",
        description="Culture and museums access (proxy via central amenities).",
        signals=[_s("restaurants_density", "high", 0.5), _s("cafes_density", "high", 0.5)],
        notes="Proxy: central amenity intensity.",
    ),
    "art_design": TagDef(
        id="art_design",
        scope="both",
        description="Creative/arts vibe (proxy via cafes + restaurants).",
        signals=[_s("cafes_density", "high", 0.6), _s("restaurants_density", "high", 0.4)],
        notes="Proxy until city adds culture venues metric.",
    ),
    "shopping": TagDef(
        id="shopping",
        scope="both",
        description="Shopping access (proxy via central amenity density).",
        signals=[_s("restaurants_density", "high", 0.5), _s("metro_density", "high", 0.5)],
    ),
    "local_market_vibe": TagDef(
        id="local_market_vibe",
        scope="both",
        description="Local market / neighborhood vibe.",
        signals=[_s("cafes_density", "high", 0.6), _s("parks_share", "high", 0.4)],
    ),
    "touristy": TagDef(
        id="touristy",
        scope="both",
        description="High tourism / landmark intensity (proxy via very high restaurant + cafe density).",
        signals=[_s("restaurants_density", "high", 0.7), _s("cafes_density", "high", 0.3)],
    ),
    "premium_feel": TagDef(
        id="premium_feel",
        scope="both",
        description="Premium/curated feel (proxy via restaurants + cafes + central access).",
        signals=[_s("restaurants_density", "high", 0.5), _s("cafes_density", "high", 0.3), _s("metro_density", "high", 0.2)],
        notes="Proxy; can be upgraded with price_index when available.",
    ),
    "value_for_money": TagDef(
        id="value_for_money",
        scope="both",
        description="Better value (proxy: lower amenity intensity -> often cheaper).",
        signals=[_s("restaurants_density", "low", 0.5), _s("cafes_density", "low", 0.3), _s("metro_density", "low", 0.2)],
        notes="Proxy; replace with price metrics when available.",
    ),
    "urban_dense": TagDef(
        id="urban_dense",
        scope="both",
        description="Dense urban fabric (proxy: high transit + amenities).",
        signals=[_s("metro_density", "high", 0.4), _s("tram_density", "high", 0.2), _s("restaurants_density", "high", 0.2), _s("cafes_density", "high", 0.2)],
    ),
    "mixed_vibes": TagDef(
        id="mixed_vibes",
        scope="both",
        description="Mixed vibe (proxy: balanced amenities + parks).",
        signals=[_s("restaurants_density", "high", 0.4), _s("parks_share", "high", 0.6)],
        notes="Proxy for 'mixed' until more diverse signals exist.",
    ),
    "young_professionals": TagDef(
        id="young_professionals",
        scope="both",
        description="Young professionals (proxy via cafes + transit).",
        signals=[_s("cafes_density", "high", 0.6), _s("metro_density", "high", 0.4)],
    ),
    "students": TagDef(
        id="students",
        scope="both",
        description="Student vibe (proxy via cafes + transit + nightlife).",
        signals=[_s("cafes_density", "high", 0.5), _s("metro_density", "high", 0.25), _s("bars_density", "high", 0.25)],
    ),

    # Family / quiet
    "families": TagDef(
        id="families",
        scope="both",
        description="Family-friendly (schools + childcare + parks).",
        signals=[_s("schools_density", "high", 0.4), _s("childcare_density", "high", 0.3), _s("parks_share", "high", 0.3)],
    ),
    "schools_strong": TagDef(
        id="schools_strong",
        scope="both",
        description="Strong schools access.",
        signals=[_s("schools_density", "high", 1.0)],
    ),
    "childcare_strong": TagDef(
        id="childcare_strong",
        scope="both",
        description="Strong childcare access.",
        signals=[_s("childcare_density", "high", 1.0)],
    ),
    "green_parks": TagDef(
        id="green_parks",
        scope="both",
        description="Parks / green pockets.",
        signals=[_s("parks_share", "high", 0.7), _s("parks_km2", "high", 0.3)],
    ),
    "older_quiet": TagDef(
        id="older_quiet",
        scope="both",
        description="Quieter/older vibe (proxy: low nightlife + more parks).",
        signals=[_s("bars_density", "low", 0.6), _s("restaurants_density", "low", 0.2), _s("parks_share", "high", 0.2)],
    ),
    "residential_quiet": TagDef(
        id="residential_quiet",
        scope="both",
        description="Residential and quiet (proxy: low nightlife + more green).",
        signals=[_s("bars_density", "low", 0.6), _s("restaurants_density", "low", 0.2), _s("parks_share", "high", 0.2)],
    ),
    "night_caution": TagDef(
        id="night_caution",
        scope="both",
        description="Be cautious at night (proxy: high nightlife).",
        signals=[_s("bars_density", "high", 0.7), _s("restaurants_density", "high", 0.3)],
    ),
    "busy_traffic_noise": TagDef(
        id="busy_traffic_noise",
        scope="both",
        description="Busy/noisy streets (proxy: very high transit + amenities).",
        signals=[_s("metro_density", "high", 0.4), _s("tram_density", "high", 0.2), _s("restaurants_density", "high", 0.2), _s("cafes_density", "high", 0.2)],
    ),

    # Mobility
    "metro_strong": TagDef(
        id="metro_strong",
        scope="both",
        description="Strong metro access.",
        signals=[_s("metro_density", "high", 1.0)],
    ),
    "tram_strong": TagDef(
        id="tram_strong",
        scope="both",
        description="Strong tram access.",
        signals=[_s("tram_density", "high", 1.0)],
    ),
    "train_hubs_access": TagDef(
        id="train_hubs_access",
        scope="both",
        description="Train hubs access.",
        signals=[_s("train_density", "high", 1.0)],
    ),
    "central_access": TagDef(
        id="central_access",
        scope="both",
        description="Central access (proxy: transit + amenities).",
        signals=[_s("metro_density", "high", 0.4), _s("tram_density", "high", 0.2), _s("restaurants_density", "high", 0.2), _s("cafes_density", "high", 0.2)],
    ),
    "eu_quarter_access": TagDef(
        id="eu_quarter_access",
        scope="both",
        description="EU quarter access (proxy via strong transit + central intensity).",
        signals=[_s("metro_density", "high", 0.5), _s("tram_density", "high", 0.25), _s("restaurants_density", "high", 0.25)],
        notes="Proxy; upgrade with job-center travel times later.",
    ),
    "airport_access": TagDef(
        id="airport_access",
        scope="both",
        description="Airport access (proxy via train access).",
        signals=[_s("train_density", "high", 0.7), _s("metro_density", "high", 0.3)],
        notes="Proxy; upgrade with explicit airport travel times later.",
    ),
    "car_friendly": TagDef(
        id="car_friendly",
        scope="both",
        description="Easier by car (proxy: lower tram/metro density, larger zones).",
        signals=[_s("metro_density", "low", 0.4), _s("tram_density", "low", 0.4), _s("area_km2", "high", 0.2)],
    ),
    "bike_friendly": TagDef(
        id="bike_friendly",
        scope="both",
        description="Bike-friendly (proxy: more parks + balanced density).",
        signals=[_s("parks_share", "high", 0.6), _s("tram_density", "high", 0.2), _s("metro_density", "high", 0.2)],
        notes="Proxy; upgrade with bike-lane network later.",
    ),

    # Housing stock (proxy)
    "apartments_more": TagDef(
        id="apartments_more",
        scope="both",
        description="More apartments (proxy: dense + central).",
        signals=[_s("urban_dense_proxy", "high", 1.0)],
        notes="Uses derived density proxy.",
    ),
    "houses_more": TagDef(
        id="houses_more",
        scope="both",
        description="More houses (proxy: quieter + greener, less dense).",
        signals=[_s("parks_share", "high", 0.5), _s("metro_density", "low", 0.25), _s("tram_density", "low", 0.25)],
        notes="Proxy; replace with housing stock metrics later.",
    ),
    "expats_international": TagDef(
        id="expats_international",
        scope="both",
        description="International / expat presence (proxy: central + amenities + transit).",
        signals=[_s("metro_density", "high", 0.4), _s("restaurants_density", "high", 0.3), _s("cafes_density", "high", 0.3)],
        notes="Proxy until explicit expat share metric exists.",
    ),
}


def get_tag_def(tag_id: str) -> Optional[TagDef]:
    return TAG_REGISTRY.get(tag_id)
