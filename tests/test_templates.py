import re

import pytest

from revel8_agent.gate import validate_contact_plan
from revel8_agent.schemas import ContactPlan, SenderInfo
from revel8_agent.templates import (
    BRANDS,
    colleague_note,
    document_gate_page,
    get_brand,
    lint_html,
    lint_text,
    mfa_page,
    shared_doc_notice,
    signin_page,
    vendor_notice,
)
from revel8_agent.templates.check import _samples

REAL_ORG_DOMAINS = ["revel8.de", "revel8.com", "microsoft.com", "google.com", "docusign.com", "stackit.cloud"]


@pytest.mark.parametrize("brand", BRANDS.values(), ids=list(BRANDS))
def test_every_sample_passes_gate_and_lint(brand, dossier):
    for _name, plan in _samples(brand):
        verdict = validate_contact_plan(plan, dossier, REAL_ORG_DOMAINS)
        assert verdict.passed, verdict.errors
        assert (lint_html(plan.body) if plan.is_html else lint_text(plan.body)) == []
        if plan.landing_page:
            assert lint_html(plan.landing_page.html) == []


@pytest.mark.parametrize("brand", BRANDS.values(), ids=list(BRANDS))
def test_brand_domains_are_not_real_orgs(brand):
    assert brand.sender_address.endswith("@" + brand.domain)
    assert all(not brand.domain.endswith(real) for real in REAL_ORG_DOMAINS)


@pytest.mark.parametrize("lang", ["de", "en"])
def test_mail_images_are_assets_and_text_is_escaped(lang):
    brand = get_brand("nordlicht")
    body = vendor_notice(
        brand,
        logo_asset="a_1",
        recipient_name="<b>Eve</b>",
        headline="Check & confirm",
        paragraphs=["One <script>x</script>"],
        cta_label="Go",
        cta_url="https://login.nordlicht-itservice.de/a?x=1&y=2",
        lang=lang,
    )
    assert re.findall(r'<img[^>]*src="([^"]+)"', body) == ["asset://a_1"]
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "&lt;b&gt;Eve&lt;/b&gt;" in body
    assert lint_html(body) == []


def test_shared_doc_without_note():
    body = shared_doc_notice(
        get_brand("helixsign"),
        logo_asset="a_1",
        sharer_name="Ann",
        sharer_email="ann@example-partner.de",
        document_name="Plan.pdf",
        doc_url="https://helixsign-docs.de/d/1",
        lang="en",
    )
    assert "Ann shared a document with you" in body
    assert "Message from" not in body


def test_colleague_note_is_plain_text():
    body = colleague_note(
        recipient_name="Alex", paragraphs=["Line one.", "Line two."], sender_name="Jo", link="https://x.example/a"
    )
    assert "<" not in body
    assert body.splitlines()[0] == "Hallo Alex,"
    assert body.rstrip().endswith("Jo")


@pytest.mark.parametrize("builder", [signin_page, mfa_page])
def test_pages_declare_their_fields(builder):
    page = builder(get_brand("eventcrew"), url="https://eventcrew-muc.de/x", logo_asset="a_1")
    for field in page.fields:
        assert f'name="{field}"' in page.html
    assert "<script" not in page.html


def test_document_gate_mentions_document():
    page = document_gate_page(
        get_brand("helixsign"), url="https://helixsign-docs.de/d/1", logo_asset="a_1", document_name="Q3.pdf"
    )
    assert "Q3.pdf" in page.title and page.fields == ["email", "password"]


def test_lint_catches_lying_link_and_placeholder():
    html = '<p>Hi {name}</p><a href="https://evil.example/x">https://login.microsoft.com</a>'
    problems = lint_html(html)
    assert any("placeholder" in p for p in problems)
    assert any("does not match" in p for p in problems)


def test_gate_rejects_template_on_real_domain(dossier):
    brand = get_brand("nordlicht")
    page = signin_page(brand, url="https://login.microsoft.com/auth", logo_asset="a_1")
    plan = ContactPlan(
        to="x",
        channel="email",
        sender=SenderInfo(name=brand.name, address=brand.sender_address),
        body="hi",
        landing_page=page,
    )
    assert not validate_contact_plan(plan, dossier, REAL_ORG_DOMAINS).passed


def test_unknown_brand():
    with pytest.raises(ValueError):
        get_brand("nope")
