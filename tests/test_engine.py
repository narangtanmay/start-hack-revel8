from datetime import datetime

import pytest

from revel8_agent.engine import estimate_score, timing

TODAY = datetime(2026, 11, 21)


@pytest.mark.parametrize("recency,expected", [
    ("2026-10-28", "past"), ("2026-07", "past"), ("July 16, 2026", "past"), ("16 July 2026", "past"),
    ("2026 Q1", "past"), ("2025", "past"), ("2026-12-10", "upcoming"), ("2027-03", "upcoming"),
    ("upcoming", "upcoming"), ("2026", "this-year"), ("unknown", "undated"),
])
def test_timing_labels(recency: str, expected: str) -> None:
    assert timing(recency, TODAY) == expected


def test_estimate_score() -> None:
    assert estimate_score({"incidents": []})["results_points"] == 0
    hit = estimate_score({"incidents": [{"touch": 4, "type": "credentials", "source": "api event"}]})
    assert hit["incident"] and hit["first_incident_touch"] == 4 and hit["results_points"] == 22.5
