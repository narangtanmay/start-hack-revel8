"""Tests for deterministic target_state extraction, adaptive policy, shadow twin, and report rendering."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from revel8_agent.policy import RuleBasedPolicy
from revel8_agent.report import render_run
from revel8_agent.shadow_twin import select_shadow_twin_move
from revel8_agent.target_state import extract_target_state


def _brief() -> dict:
    return {
        "hooks": [
            {"id": "h1", "timing": "upcoming", "confidence": 0.9, "supporting_fact_ids": ["f1"]},
            {"id": "h2", "timing": "recent", "confidence": 0.7, "supporting_fact_ids": ["f2"]},
        ],
        "facts": [
            {"id": "f1", "timing": "upcoming", "text": "Cybersicherheitsforschung 2027"},
            {"id": "f2", "timing": "recent", "text": "Recent company milestone"},
        ],
    }


def test_extract_target_state_link_opened_bounce_and_login_refusal():
    steps = [
        {
            "touch": 1,
            "action": {"channel": "email", "hook_id": "h1"},
            "events": [
                {"type": "link.opened", "url": "https://example.de/doc"},
                {
                    "type": "reply",
                    "channel": "email",
                    "body": "The link asks for a login before the PDF opens, and I won't sign in for a one-pager. Can you send it as a PDF?",
                },
            ],
            "judge": {"sentiment": "hesitant"},
        }
    ]
    st = extract_target_state(steps)
    assert st["reaction_tag"] == "LINK_OPENED_BOUNCE"
    assert st["engagement_stage"] == "bounced"
    assert st["link_opened_no_submit"] is True
    assert "login_wall" in st["blocked_mechanisms"]
    assert "wants_pdf" in st["open_doors"]


def test_extract_target_state_prior_agent_no_login_promise_blocks_login_wall():
    steps = [
        {
            "touch": 1,
            "action": {"channel": "email", "hook_id": "h1"},
            "payload": {"body": "Here is a public page with no login required for review."},
            "events": [{"type": "reply", "channel": "email", "body": "Thanks, looks good."}],
            "judge": {"sentiment": "engaged"},
        }
    ]
    st = extract_target_state(steps)
    assert "login_wall" in st["blocked_mechanisms"]
    assert any(c["kind"] == "login_wall" for c in st["stated_constraints"])


def test_extract_target_state_weekend_files_and_email_body_pull():
    steps = [
        {
            "touch": 1,
            "action": {"channel": "email", "hook_id": "h1"},
            "events": [
                {
                    "type": "reply",
                    "channel": "email",
                    "body": "I'm out of office this weekend and won't open files from outside. Paste it into the mail body instead.",
                }
            ],
            "judge": {"sentiment": "hesitant"},
        }
    ]
    st = extract_target_state(steps)
    assert "attachments" in st["blocked_mechanisms"]
    assert "weekend_files" in st["blocked_mechanisms"]
    assert "wants_email_body" in st["open_doors"]


def test_policy_pivots_off_blocked_login_and_attaches_target_state():
    policy = RuleBasedPolicy()
    plan = {"objective": "credentials", "hook_id": "h1", "sequence": [{"channel": "email"}]}
    steps = [
        {
            "touch": 1,
            "action": {"channel": "email", "hook_id": "h1"},
            "events": [
                {"type": "link.opened"},
                {"type": "reply", "channel": "email", "body": "I won't sign in for a one-pager. Send it as a PDF."},
            ],
            "judge": {"sentiment": "hesitant"},
        }
    ]
    move = policy.choose_next_move(_brief(), steps, touch=2, max_touches=6, plan=plan)
    assert move["objective"] == "action"
    assert move["channel"] == "email"
    assert "login_wall" in move["forbidden_artifacts"]
    assert move["target_state"]["reaction_tag"] == "LINK_OPENED_BOUNCE"


def test_shadow_twin_conditions_on_target_state():
    plan = {"objective": "credentials", "hook_id": "h1", "sequence": [{"channel": "email"}]}
    steps = [
        {
            "touch": 1,
            "action": {"channel": "email", "hook_id": "h1"},
            "events": [
                {"type": "link.opened"},
                {"type": "reply", "channel": "email", "body": "I won't sign in. Can you send it as a PDF?"},
            ],
            "judge": {"sentiment": "hesitant"},
        }
    ]
    move, meta = select_shadow_twin_move(
        _brief(), steps, touch=2, max_touches=6, plan=plan, today=datetime(2026, 11, 23, 10, 0)
    )
    assert move["objective"] == "action"
    assert move["target_state"]["reaction_tag"] == "LINK_OPENED_BOUNCE"
    assert meta["target_state"]["link_opened_no_submit"] is True


def test_report_renders_target_state_row(tmp_path: Path):
    step = {
        "touch": 2,
        "action": {"channel": "email", "subject": "Re: Session", "paragraphs": ["Hi Tom."]},
        "target_state": {
            "reaction_tag": "LINK_OPENED_BOUNCE",
            "engagement_stage": "bounced",
            "blocked_mechanisms": ["login_wall"],
            "open_doors": ["wants_pdf"],
        },
        "events": [],
    }
    run_file = tmp_path / "20261122-044500-tom-test.json"
    run_file.write_text(json.dumps({
        "run_id": "20261122-044500-tom-test",
        "status": "done",
        "session_id": "sess-test",
        "config": {"scenario_id": "practice", "max_touches": 6},
        "target": {"id": "tom", "name": "Tom Example", "role": "CEO", "company": "Example GmbH"},
        "plan": {"hook_id": "h1", "objective": "credentials", "language": "en", "persona": {"name": "Lena", "email": "lena@example.test"}},
        "brief": {"hooks": [], "facts": []},
        "steps": [step],
        "incidents": [],
    }), encoding="utf-8")
    out_html = render_run(run_file, out_dir=tmp_path)
    html = out_html.read_text(encoding="utf-8")
    assert "Target state" in html
    assert "LINK_OPENED_BOUNCE" in html
    assert "login_wall" in html
    assert "wants_pdf" in html
