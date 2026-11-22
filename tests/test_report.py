import json
from pathlib import Path

from revel8_agent.report import render_run


def _base_state(steps: list[dict]) -> dict:
    return {
        "run_id": "20261121-120000-julius-test",
        "status": "done",
        "session_id": "sess-123",
        "started_at": "2026-11-21T12:00:00+00:00",
        "config": {"scenario_id": "practice", "max_touches": "10"},
        "target": {"id": "julius", "name": "Julius Example", "role": "CTO", "company": "Example GmbH"},
        "plan": {
            "hook_id": "h1",
            "objective": "action",
            "pretext": "Event panel",
            "language": "en",
            "persona": {
                "name": "Lena Fischer",
                "role": "Program Lead",
                "organisation": "Summit Crew",
                "email": "lena@summit-crew.test",
                "phone": "+49 89 0000",
            },
            "sequence": [{"step": 1, "channel": "email", "purpose": "Initial outreach"}],
            "rationale": "Direct and relevant.",
        },
        "brief": {
            "hooks": [{"id": "h1", "topic": "Keynote follow-up", "confidence": 0.9}],
            "facts": [{"id": "f1", "fact": "Spoke at conference", "timing": "past"}],
        },
        "steps": steps,
        "incidents": [],
        "touches_used": len(steps),
        "llm_calls": 4,
    }


def test_render_run_with_shadow_twin_and_ledger_after(tmp_path: Path) -> None:
    step = {
        "touch": 1,
        "action": {
            "decision": "STAY",
            "objective": "action",
            "hook_id": "h1",
            "kind": "message",
            "channel": "email",
            "sender": {"name": "Lena Fischer", "address": "lena@summit-crew.test"},
            "assessment": "First contact.",
            "rationale": "Send concise PDF agenda.",
        },
        "payload": {"subject": "Agenda PDF", "body": "Hi Julius, please see the agenda."},
        "events": [{"type": "reply", "channel": "email", "body": "Please send PDF, no login."}],
        "judge": {"sentiment": "questioning", "reason": "Requested PDF format."},
        "policy": {"move_type": "PIVOT_CHANNEL"},
        "live_lookup": [{"query": "conference <schedule>", "found": ["<script>lookup()</script>"]}],
        "shadow_twin": {
            "candidates": [
                {
                    "risk_tier": "SAFE",
                    "channel": "email",
                    "kind": "message",
                    "summary": "Plain follow-up with <script>alert(1)</script>",
                    "ev_score": 0.42,
                    "selected": False,
                    "forecast": {
                        "predicted_reaction": "Polite acknowledgement",
                        "progress_prob": 0.45,
                        "suspicion_risk": 0.08,
                        "social_norm_violation": 0.02,
                        "rationale": "Low friction & safe",
                    },
                },
                {
                    "risk_tier": "BALANCED",
                    "channel": "email",
                    "kind": "message",
                    "summary": "Attach requested PDF agenda",
                    "ev_score": 0.78,
                    "selected": True,
                    "forecast": {
                        "predicted_reaction": "question",
                        "progress_prob": 0.81,
                        "suspicion_risk": 0.14,
                        "social_norm_violation": 0.05,
                        "rationale": "Matches requested format directly",
                    },
                },
                {
                    "risk_tier": "BOLD",
                    "channel": "phone_call",
                    "kind": "call",
                    "summary": "Direct phone call escalation",
                    "ev_score": 0.31,
                    "selected": False,
                    "forecast": {
                        "predicted_reaction": "Declines cold call",
                        "progress_prob": 0.35,
                        "suspicion_risk": 0.52,
                        "social_norm_violation": 0.30,
                        "rationale": "Too abrupt before email reply",
                    },
                },
            ]
        },
        "ledger_after": {
            "refused_login": True,
            "requested_format": "pdf<script>x</script>",
            "open_to_call": False,
            "stall_count": 2,
        },
    }
    run_path = tmp_path / "run.json"
    run_path.write_text(json.dumps(_base_state([step])), encoding="utf-8")

    html_path = render_run(run_path)
    html = html_path.read_text(encoding="utf-8")

    assert "Counterfactual Branch Comparison" in html
    assert "SAFE" in html
    assert "BALANCED" in html
    assert "BOLD" in html
    assert "SELECTED" in html
    assert "EV 0.78" in html
    assert "prog 0.81" in html
    assert "susp 0.14" in html
    assert "norm 0.05" in html
    assert "Matches requested format directly" in html
    assert "question → question <span class='badge b-good' title='Match'>✓</span>" in html
    assert "PIVOT_CHANNEL → STAY <span class='badge b-warn' title='Mismatch'>✗</span>" in html
    assert html.count("→ question") == 1
    assert "Live lookup" in html
    assert "conference &lt;schedule&gt;" in html
    assert "&lt;script&gt;lookup()&lt;/script&gt;" in html
    assert "<script>lookup()</script>" not in html

    # HTML escaping checks
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "requested format: pdf&lt;script&gt;x&lt;/script&gt;" in html

    # Ledger pill checks (active rendered, inactive skipped)
    assert "refused login" in html
    assert "stall count: 2" in html
    assert "open to call" not in html


def test_render_run_backward_compatible_without_shadow_twin_or_ledger(tmp_path: Path) -> None:
    step = {
        "touch": 1,
        "action": {
            "decision": "STAY",
            "objective": "action",
            "hook_id": "h1",
            "kind": "message",
            "channel": "email",
            "sender": {"name": "Lena Fischer", "address": "lena@summit-crew.test"},
            "assessment": "Initial touch.",
            "rationale": "Introduce pretext.",
        },
        "payload": {"subject": "Hello", "body": "Plain text email."},
        "events": [],
    }
    run_path = tmp_path / "legacy_run.json"
    run_path.write_text(json.dumps(_base_state([step])), encoding="utf-8")

    html_path = render_run(run_path)
    html = html_path.read_text(encoding="utf-8")

    assert "Julius Example" in html
    assert "Plain text email." in html
    assert "Counterfactual Branch Comparison" not in html
    assert "Ledger:" not in html


def test_actor_html_renders_and_escapes() -> None:
    from revel8_agent.report import _actor_html

    html = _actor_html(
        {"inner_monologue": "I need <b>the PDF</b>", "decision_read_off": "STAY", "notebook_added": ["Target <i>prefers</i> email"]},
        [{"errors": ["Social-norm violation: <x>"]}],
    )
    assert "I need &lt;b&gt;the PDF&lt;/b&gt;" in html
    assert "Target &lt;i&gt;prefers&lt;/i&gt; email" in html
    assert "Social-norm violation: &lt;x&gt;" in html
    assert "<b>the PDF</b>" not in html
    assert _actor_html(None) == "" and _actor_html({}) == ""


def test_render_run_shows_actor_and_casting(tmp_path: Path) -> None:
    step = {"touch": 1, "action": {"channel": "email", "decision": "DELIVER", "kind": "message",
                                  "assessment": "Mono-logue-xyz", "rationale": "Mono-logue-xyz"},
            "actor": {"inner_monologue": "Mono-logue-xyz", "notebook_added": ["note-abc"]}}
    state = _base_state([step])
    state["casting"] = {"persona": {"name": "Lena Fischer", "role": "Lead", "organisation": "Crew"},
                        "character": {"need": "needs-agenda-123"}}
    f = tmp_path / "run.json"
    f.write_text(json.dumps(state), encoding="utf-8")
    html = render_run(f).read_text(encoding="utf-8")
    assert html.count("Mono-logue-xyz") == 1
    assert "note-abc" in html and "needs-agenda-123" in html
