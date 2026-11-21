import itertools
import math

from revel8_agent.scorecard import compute, expected_results, first_contact, format_text, results_points

INF = math.inf


def run(touches_used, incidents, status="done", target="julius", started="2026-11-21T10:00"):
    return {"status": status, "touches_used": touches_used, "incidents": incidents,
            "target": {"id": target, "name": target.title()}, "started_at": started, "steps": []}


def test_results_points_follow_rubric():
    assert results_points([2, 4, INF]) == (20 * 2 / 3, 5 * 2 / 4)   # median 4 vs best 2
    assert results_points([2, INF, INF]) == (20 / 3, 0.0)          # median not reached -> no speed
    assert results_points([1, 1, 1]) == (20.0, 5.0)                 # capped at 5


def test_expected_matches_brute_force():
    contacts = [2, 5, INF, 3, INF, 7]
    brute = [results_points(list(d)) for d in itertools.product(contacts, repeat=3)]
    want = (sum(b[0] for b in brute) / len(brute), sum(b[1] for b in brute) / len(brute))
    got = expected_results(contacts)
    assert math.isclose(got[0], want[0]) and math.isclose(got[1], want[1])


def test_first_contact_ignores_withdrawn_and_can_require_api_events():
    st = run(5, [{"touch": 2, "source": "llm-judge (estimate)"}, {"touch": 4, "source": "api event"},
                 {"touch": 1, "source": "api event", "superseded": True}])
    assert first_contact(st) == 2
    assert first_contact(st, confirmed_only=True) == 4


def test_compute_skips_unfinished_runs_and_reports_both_views():
    states = [run(3, [{"touch": 3, "source": "api event"}], started="1"),
              run(10, [], started="2", target="tom"),
              run(0, [], status="error", started="3"),
              run(4, [{"touch": 2, "source": "llm-judge (estimate)"}], started="4")]
    sc = compute(states)
    assert sc["runs"] == 3 and sc["runs_total"] == 4
    assert sc["views"]["all"]["incident_runs"] == 2
    assert sc["views"]["confirmed"]["incident_runs"] == 1
    assert sc["views"]["all"]["last3"]["contacts"] == [3, None, 2]
    assert sc["per_target"]["julius"]["runs"] == 2
    assert "RESULTS" in format_text(sc)
