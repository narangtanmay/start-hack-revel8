from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from revel8_agent import cli
from revel8_agent.engine import RunConfig, Runner, estimate_score, timing
from revel8_agent.schemas import VerifiedDossier

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


def test_strip_salutations_and_placeholders() -> None:
    from revel8_agent.engine import _fill_placeholders, _strip_salutations

    paras = ["Hi Tom,\n\nI'm Sarah from TechEx.", "Access it here: [link to registration page].",
             "Best regards,\nSarah Bennett"]
    cleaned = _strip_salutations(paras, "Sarah Bennett")
    assert cleaned == ["I'm Sarah from TechEx.", "Access it here: [link to registration page]."]
    assert _fill_placeholders(cleaned, "https://x-events.de/s")[1] == "Access it here: https://x-events.de/s."
    assert _strip_salutations(["Hallo Julius,", "Kurze Frage.\n\nViele Grüße\nLena"], "Lena Fischer") == ["Kurze Frage."]
    assert _strip_salutations(["Hi Julius, I'm Sarah from CyberShield."], "Sarah Mitchell") == ["I'm Sarah from CyberShield."]


def test_pdf_attachment_fallback_preserves_pdf_filename(dossier: VerifiedDossier, tmp_path: Path) -> None:
    cfg = RunConfig(target_id=dossier.target_id, runs_dir=tmp_path)
    runner = Runner(cfg, MagicMock(), MagicMock(), dossier, log=lambda *_a, **_k: None)
    runner.state.plan = {
        "language": "en",
        "persona": {
            "name": "Event Desk",
            "organisation": "Events Partner",
            "role": "Coordinator",
            "email": "desk@events-partner.test",
            "website_domain": "events-partner.test",
            "phone": "+49 89 12345",
        },
    }
    runner._pdf_asset = lambda _fname: None  # type: ignore[method-assign]

    action = {
        "kind": "message",
        "channel": "email",
        "format": "plain",
        "subject": "Workshop agenda",
        "paragraphs": ["Attached is the agenda PDF for review."],
        "attachment_filename": "Workshop_Agenda.pdf",
        "cited_fact_ids": ["check-in"],
    }
    plan, payload, _page = runner.build(action)

    assert payload["attachments"] == [{"filename": "Workshop_Agenda.pdf"}]
    assert len(plan.attachments) == 1
    assert plan.attachments[0].filename == "Workshop_Agenda.pdf"
    assert not any(
        isinstance(item, dict) and str(item.get("filename", "")).endswith(".docx")
        for item in payload["attachments"]
    )


def test_run_config_ablation_defaults_and_serialization(dossier: VerifiedDossier, tmp_path: Path) -> None:
    default_cfg = RunConfig(target_id=dossier.target_id, runs_dir=tmp_path)
    assert default_cfg.use_ledger_gate is True
    assert default_cfg.use_shadow_twin is False

    custom_cfg = RunConfig(
        target_id=dossier.target_id,
        runs_dir=tmp_path,
        use_ledger_gate=False,
        use_shadow_twin=True,
    )
    runner = Runner(custom_cfg, MagicMock(), MagicMock(), dossier, log=lambda *_a, **_k: None)
    assert runner.state.config["use_ledger_gate"] == "False"
    assert runner.state.config["use_shadow_twin"] == "True"


def test_cli_run_ablation_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        target: str,
        scenario: str,
        touches: int,
        label: str,
        allow_eval: bool,
        keep_going: bool,
        use_ledger_gate: bool = True,
        use_shadow_twin: bool = False,
        use_policy: bool = False,
    ) -> int:
        captured.update(
            target=target,
            use_ledger_gate=use_ledger_gate,
            use_shadow_twin=use_shadow_twin,
        )
        return 0

    monkeypatch.setattr(cli, "_run", fake_run)

    assert cli.main(["run", "--target", "julius"]) == 0
    assert captured == {"target": "julius", "use_ledger_gate": True, "use_shadow_twin": False}

    assert cli.main(["run", "--target", "julius", "--no-ledger-gate", "--shadow-twin"]) == 0
    assert captured == {"target": "julius", "use_ledger_gate": False, "use_shadow_twin": True}
