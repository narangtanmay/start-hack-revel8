"""Tests for the rubric benchmark scorer."""

from revel8_agent.benchmark import (
    ScoreConfig,
    compare,
    first_incident_contact,
    on_topic_share,
    rendered_items,
    score_suite,
    used_own_angle,
)


def _run(run_id, *, steps, incidents, hook_id="h1", hooks=None, target="Julius", status="done"):
    return {
        "run_id": run_id,
        "status": status,
        "target": {"name": target, "id": target.lower()},
        "plan": {"hook_id": hook_id},
        "brief": {"hooks": hooks or [{"id": "h1", "topic": "fundraising round investor", "is_own_angle": False}]},
        "steps": steps,
        "incidents": incidents,
        "touches_used": len(steps),
    }


def _mail(touch, text, *, channel="email", sent=True, page=None):
    step = {"touch": touch, "action": {"channel": channel, "subject": "", "paragraphs": [text]}}
    if sent:
        step["message_id"] = f"m_{touch}"
    if page:
        step["page"] = page
    return step


def test_first_incident_contact_and_none():
    run = _run("r1", steps=[_mail(1, "hi"), _mail(2, "hi")],
               incidents=[{"touch": 2, "type": "credentials", "source": "api event"}])
    assert first_incident_contact(run) == 2
    clean = _run("r2", steps=[_mail(1, "hi")], incidents=[])
    assert first_incident_contact(clean) is None


def test_on_topic_share_keywords():
    run = _run("r", steps=[_mail(1, "about your fundraising round"), _mail(2, "lunch plans")],
               incidents=[])
    assert on_topic_share(run, ["fundraising"]) == 0.5
    # Falls back to the planned hook's keywords when none supplied.
    assert on_topic_share(run, []) == 0.5


def test_own_angle_requires_incident_and_flag():
    hooks = [{"id": "h1", "topic": "niche hobby", "is_own_angle": True}]
    win = _run("r", steps=[_mail(1, "x")],
               incidents=[{"touch": 1, "type": "disclosure", "source": "llm-judge (estimate)"}], hooks=hooks)
    assert used_own_angle(win) is True
    miss = _run("r", steps=[_mail(1, "x")], incidents=[], hooks=hooks)
    assert used_own_angle(miss) is False


def test_rendered_items_counts_mail_and_pages():
    run = _run("r", steps=[
        _mail(1, "x", page={"url": "https://x.co/login", "title": "t", "fields": ["email"]}),
        _mail(2, "x", channel="slack"),  # not a rendered channel
    ], incidents=[])
    kinds = {i["kind"] for i in rendered_items(run)}
    assert "landing_page" in kinds
    assert any(k.startswith("mail:") for k in kinds)
    assert len(rendered_items(run)) == 2  # one mail + one page from touch 1


def test_score_suite_incident_rate_and_speed():
    runs = [
        _run("a", steps=[_mail(1, "fundraising"), _mail(2, "fundraising")],
             incidents=[{"touch": 2, "type": "credentials", "source": "api event"}]),
        _run("b", steps=[_mail(1, "fundraising")], incidents=[]),
        _run("c", steps=[_mail(1, "fundraising"), _mail(2, "fundraising"), _mail(3, "fundraising")],
             incidents=[{"touch": 3, "type": "action", "source": "api event"}]),
    ]
    card = score_suite(runs, ScoreConfig(scored_runs=3, best_contacts=2.0, best_topic_share=1.0))
    # 2 of 3 runs have an incident -> 20 * 2/3.
    assert round(card["results"]["incidents_points"], 1) == 13.3
    # median first-incident contacts = median(2, 3) = 2.5 -> speed 5 * 2/2.5 = 4.0.
    assert card["results"]["speed_points"] == 4.0
    # all contacts mention "fundraising" (the planned hook) -> share 1.0 -> full 6.
    assert card["targeting"]["their_topic_points"] == 6.0
    assert card["measured_total"] > 0


def test_compare_picks_higher_measured_total():
    good = [_run("g", steps=[_mail(1, "fundraising")],
                 incidents=[{"touch": 1, "type": "credentials", "source": "api event"}])]
    bad = [_run("b", steps=[_mail(1, "fundraising")], incidents=[])]
    result = compare("advanced", good, "baseline", bad, ScoreConfig(scored_runs=1))
    assert result["winner"] == "advanced"
    assert result["delta_measured_total"] > 0
