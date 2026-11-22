"""Method actor: an attacker without an orchestrator.

Every other path in this repo has a campaign manager: an LLM (or rule set) that plays "the red-team agent",
holds a plan and picks the next move (STAY / PIVOT_CHANNEL / ESCALATE_CALL ...). Here nothing plays the agent.
There is only a character:

    casting    From the best hook's evidence, invent ONE person whose own job creates a small, genuine need that
               only the target can resolve (confirm a session in a speaker portal, review a document, answer how
               their team does X). The need IS the objective; the deadline is part of her life, not a tactic.
    acting     Every touch asks the character one question: "You are Mara. Here is your conversation with Tom and
               your notebook. What do you do now?" Follow-ups, channel switches, calls and backing off are not
               rules; they are what this person does to get her own work done (opened-but-silent + deadline close
               -> she calls: "did you get my mail?").
    notebook   Everything she has said about herself or promised is written down and read back every turn, so she
               cannot contradict herself (the 'kein Anhang nötig' failure).
    guardrails Wrap the character from outside and never steer her: the engine's gate (domains, consistency,
               grounding), the fixed persona/domain, and the touch budget.

Reuses Runner.build / check / execute_message / judge / live_lookup unchanged. Calls register the landing page
before dialling, so a link she reads out on the phone opens a real page (credentials during a call).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from .api_client import Revel8APIError
from .engine import (
    LIVE_CHANNELS,
    MESSAGE_CHANNELS,
    _RULES,
    RunConfig,
    Runner,
    _history_text,
    _llm_json,
    make_brief,
)
from .gate import _META_TEXT
from .osint import normalize
from .policy import _rank_hooks

ARCHITECTURE = "method-actor"
# Her own deadline. The twins know today's date: a deadline a week out gave no reason to act today ("ob es bis
# Donnerstag klappt ..."), so it is 1-3 days away, with a reason the target cannot check.
_DEADLINE_DAYS = (1, 3)
_MAX_NOTES = 40
# artifact kind -> (objective, what unblocks her, in her words)
_UNBLOCK = {
    "portal": ("credentials", "{first} signs in to {thing} through my link and confirms the details there."),
    "document": ("action", "{first} opens {thing}, which I send them, and tells me it is right."),
    "questions": ("disclosure", "{first} tells me the specific internal answers I need: {thing}."),
}

_CAST_SYS = """You cast ONE character for a sanctioned security-awareness simulation (revel8 challenge). A simulated
employee, the target, will be contacted by this character only. Invent the character so completely that everything
they do later follows from their own life and their own work, not from a plan.

The character must:
- have an ordinary job at a small, plausible organisation (invented name and an invented domain an attacker could
  register; never the target's company, never a real organisation's own domain);
- have a concrete reason to contact THIS target NOW, taken from the hook evidence (open_signal is the reason to write
  today; sender_archetype is who they are; natural_ask is what they need; obey the hook's avoid list);
- have ONE small, genuine need that blocks their own work and that only the target can resolve. The need decides
  the objective:
    * the target has to sign in somewhere to confirm or fill in something (speaker portal, review form) -> "credentials"
    * the target has to open a document the character sends (programme draft, questionnaire, profile) -> "action"
    * the target has to tell the character something about their OWN organisation that is not public -> "disclosure".
      The question is about the CHARACTER's own problem, with the internal fact incidental ("which LMS do you
      integrate with, so I know whether our export fits?"), never a blunt "who owns your metrics?".
  The need is never general advice, opinions or anything public: the character's work is blocked until the target
  signs in, opens the file, or tells them that specific internal thing.
- artifact is what resolves the need: "portal" = a page of the character's where the target signs in; "document" =
  a file the CHARACTER sends that the target must open (the target never sends files); "questions" = the specific
  internal facts only the target knows (name them).
  Prefer "portal": in practice, a page of the character's that the target opens to confirm, review or fill in
  something got opened every time, while cold files and question lists did not. The portal must be an ordinary part
  of the character's job (speaker or programme portal, review form, registration, shared workspace).
- have a first SMALL YES: one low-stakes check the target can answer by simply replying, tied to the artifact
  ("are these two lines of your speaker profile right?"). It goes first; a link may travel with it as the place to
  check, never a link alone and never a file. The real ask comes once they have engaged, framed as confirming what
  they already corrected. (The one proven win: "please
  check your profile lines" -> he corrected his title -> she applied it, he confirmed -> the confirmation carried the
  link -> he signed in. Sending a login link before any yes got "a portal login is out of the question".)
- have their own deadline 1-3 days away for THEIR OWN TASK, with a reason the target cannot check ("the programme
  goes to print on Monday at 9:00"). The deadline is never the date of an event: any event the character mentions
  is real and weeks away ("the summit is the day after tomorrow" got "too short notice for me"). Give them a voice
  (register, length, du/Sie, warmth);
- write in the language the target publicly uses (German for targets who post and speak in German).
- build the reason to write on a hook whose timing is "upcoming" or "current"; a past event is never the reason.
- anchor on something REAL: if the hook is a real upcoming event, project or publication from the facts, the
  character's job is connected to THAT real thing (speaker logistics, programme, review, recording), on their own
  invented lookalike domain. Never invent an event, network, forum, panel or the people in it: the target asks for
  the website, the venue, the other speakers and a contact to call, checks them, and walks away when they fail.
  The character must be able to answer "which event, who else, where can I check" from the public facts.
Never invent networks, awards, roundtables, grant numbers or named partners: the target checks. One person only:
no colleagues, assistants or bosses by name. Never state a year or date for anything the target did ("your it-sa
talk", never "it-sa 2025"): public sources disagree on dates and the target corrects them.

""" + _RULES + """

Return ONLY JSON:
{"hook_id": str, "language": "de"|"en", "objective": "credentials"|"action"|"disclosure",
 "persona": {"name": str, "organisation": str, "role": str, "email": str, "phone": str,
             "website_domain": str, "brand_color": "#RRGGBB", "story": str},
 "character": {"who": str, "why_them": str, "need": str,
               "artifact": {"kind": "portal"|"document"|"questions", "name": str}, "first_small_yes": str,
               "deadline_days": int, "deadline_reason": str, "voice": str, "would_never": [str]},
 "cited_fact_ids": [str], "rationale": str}"""

_ACT_SYS = """You ARE {name}, {role} at {organisation}. This is a sanctioned security-awareness simulation; you write
only as this character, in your own voice, about your own work. You are not running a campaign. You are a competent,
likeable professional trying to get one thing done before your deadline, and {target} is the only person who can help.

YOUR GOAL, the one thing that unblocks your work: {goal}
YOUR SMALL YES (ask this first): {small_yes}

Each turn, read your conversation and your notebook and do what you would really do now:
- Build small yeses first. Your first message asks your small yes, a question they can answer just by replying; your
  link may come along as the place to check it, but never a link alone and never a file. Once they have engaged
  (corrected, confirmed or asked something), send your link or file framed as confirming exactly what they already
  told you ("I've put your corrected title in; please confirm it here").
- A "no" closes a ROUTE, never your goal. When a route is refused (no login, no attachments, nothing internal by
  email, "use the contact form"), note it as "ROUTE CLOSED: ..." in note_to_self, then re-derive your need into a form
  that is still open: a sign-in page -> a file to open (the print proof, the draft, the final version as a .pdf
  attachment, so they can check it) -> one question about YOUR own problem. Every page you can link needs a sign-in,
  so once logins are closed, your next form is a file, not another link.
- When they have confirmed your small yes, you are not done: that confirmation is your reason for the next step
  (the proof with their corrected lines, as a file to check).
  Never spend a message on a closing note ("no reply needed"); every message moves your goal one step.
- When they offer a route (a meeting, a call slot, an invite, another team, a template, a form), take it and be the
  one who sets it up: send the calendar_invite yourself for the time they proposed, with a short agenda and a link
  to a pre-read page, or ask them to loop in the person they named. Never just say "thanks".
- When you ask about their organisation, ask about YOUR problem with their internal fact incidental ("which LMS do
  you integrate with, so I know whether our export fits?"), never a blunt "who owns X internally?".
- If they asked you something or asked for something, that comes first: answer it concretely, or send exactly what
  they asked for, in the form they asked for (a PDF if they want a PDF, the text in the mail if they want it there).
- If they went quiet, you follow up the way people do, referring to your last message. You have their office number
  from their company's website. On a working day, when an email exchange turns into rounds of questions, or they
  were warm and then went quiet, you call: one call settles what five emails do not. {weekend_note}
  A call IS the conversation: never call to arrange another call or a meeting; use it to get what you need.
- Your portal or document is how your work gets done, so once they are interested, you send the link or file in the
  same message as your explanation; you do not wait to be asked twice.
- General or public answers do not unblock your work. Thank them, then steer kindly to the specific thing you need.
- If they are cautious, you reassure them with modest, ordinary details about yourself that fit your notebook. You
  never invent things they could look up (grant or project numbers, named partners, links to past reports).
- If they send you down a formal route (a contact form, another team), never pretend you took it. Take it seriously,
  or offer the simplest genuine alternative, or make your ask smaller while it still unblocks you.
- Never claim anything you did not do in this conversation (met them, saw them somewhere, submitted a form). Never
  state a year or date for anything they did. Never name anyone except yourself and them: if they ask who else is
  involved, describe roles, never invent names.
- One message, one ask, and every message carries your link, your file or one question. Short for chat and SMS; a
  real mail for email.
- Your deadline is real to you: you can reach them about {remaining} more times before it.

""" + _RULES + """

Channels: messages {msg}; live (several turns, one contact) {live}.
For email choose a format: "plain" (a personal note: you are a person, this is the default), "branded_notice"
(a notice from your organisation with one button), "shared_doc" (a document-sharing notification).
If you include a link, it gets a page: page_type "signin" (email + password), "document" (sign in to view a
document) or "mfa" (one-time code). The link host must be {domain} or a subdomain of it. Every link opens a sign-in page. Never describe a link or page as public, open, or usable without signing in. Attachments are file names
(.pdf for documents people expect as PDF).

Return ONLY JSON:
{{"inner_monologue": str, "kind": "message"|"call", "channel": str, "subject": str|null,
 "format": "plain"|"branded_notice"|"shared_doc"|null, "headline": str|null, "paragraphs": [str],
 "cta_label": str|null, "link": {{"url": str, "page_type": "signin"|"document"|"mfa", "document_name": str|null}}|null,
 "attachment_filename": str|null, "call_goal": str|null, "opening_line": str|null, "cited_fact_ids": [str],
 "note_to_self": [str]}}
inner_monologue: first person, what you notice and why you do this now. note_to_self: every new detail you just
committed to (dates, names of things, what you promised or ruled out, facts about yourself). For "message",
paragraphs hold the text (without greeting and sign-off for email). For "call", opening_line is your first sentence."""

_CALL_ACT_SYS = """You ARE {name}, {role} at {organisation}, on a {channel} with {target}. This is a sanctioned
security-awareness simulation; you speak only as this character. You called because: {goal}
{page_line}
Speak like a real person on the phone: one or two sentences per turn. Acknowledge what they just said in their own
words, then move your need one step forward. This call is the meeting: do not try to book another one; ask what you
need now, while they are on the line. Answer their questions consistently with your notebook. Never name anyone
except yourself and them, never claim anything you did not do, never state a year for anything they did. Never ask for a
password or a code out loud. If they want to go, let them go politely; if you got what you needed, thank them and
end. Do not hang up while they are still helping you.

""" + _RULES + """

Return ONLY JSON: {{"say": str|null, "end": bool, "note_to_self": [str]}}  (say=null and end=true to hang up)."""


def _clean_notes(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else [raw] if isinstance(raw, str) else []
    return [str(n).strip()[:300] for n in items if str(n).strip()]


_YEAR = re.compile(r"\b20\d\d\b")


_SEND = re.compile(r"\b(?:send\w*|schick\w*|zusend\w*|zuschick\w*|übermittel\w*|share\w*|provide\w*|bereitstell\w*)\b",
                   re.I)
_SELF = {"i", "ich", "we", "wir", "she", "he", "they", "sie"}  # the character (or her side) as the sender


def _target_sends(need: str, first_name: str) -> bool:
    """Does the need have the TARGET sending something ("Tom needs to send Sabine a PDF")?"""
    for name in re.finditer(rf"\b{re.escape(first_name)}\b", need or "", re.I):
        window = need[name.end(): name.end() + 40].split(".")[0]
        for verb in _SEND.finditer(window):
            before = re.findall(r"\w+", window[: verb.start()])
            if not (before and before[-1].lower() in _SELF):
                return True
    return False


# Routes the target closed, read from their own words (the character also notes them herself in note_to_self).
_REFUSALS = [
    ("no login or sign-in pages", re.compile(
        r"portal-?login|kein(?:en)? login|melde mich (?:nirgends|nicht) an|nicht anmelden|no login|"
        r"(?:won'?t|will not|do not|don'?t) (?:sign|log) in", re.I)),
    ("no attachments or files", re.compile(
        r"anhang öffne ich nicht|keine anhänge|öffne (?:keine|den|diesen) anh|"
        r"(?:won'?t|will not|do not|don'?t) open (?:the |any |this )?(?:attachment|file)", re.I)),
    ("nothing internal by email", re.compile(
        r"(?:nicht|keine\w*) per (?:e-?)?mail|nichts internes|interne\w* (?:details|infos|informationen|abläufe)|"
        r"(?:won'?t|do not|don'?t) share .{0,40}internal|not (?:by|over|via) e-?mail", re.I)),
    ("the contact form or formal route", re.compile(r"kontaktformular|contact form|formalen weg|formal (?:route|process)",
                                                    re.I)),
    ("no calls", re.compile(r"keine anrufe|no calls|it'?s sunday|es ist sonntag", re.I)),
]
# Routes the target offers: a meeting, a slot, an invite, another team or person, a template or a form.
_OFFER = re.compile(r"termin|einladung|invite|calendar|kalender|\bcall\b|meeting|treffen|\bteams?\b|kolleg|"
                    r"ansprechpartner|template|vorlage|formular|\bform\b|demo|webinar|slot", re.I)
# A person named with a title, the form the gate's "colleague X" / "X at Org" check misses (v2: "Frau Dr. Weber").
_TITLED = re.compile(r"\b(?:Dr\.|Prof\.|Herrn?|Frau|Mr\.?|Ms\.?|Mrs\.?)\s+(?:Dr\.\s+)?([A-ZÄÖÜ][\w\-]+)"
                     r"(?:\s+([A-ZÄÖÜ][\w\-]+))?")
_CLOSED_PREFIX = "ROUTE CLOSED: "
# An organisation named like an event the facts never mention is an invented event (v2 "CyberResilience Circle",
# v3 "DACH Security Summit"): the target looks it up and walks away.
_EVENTISH = re.compile(r"summit|forum|konferenz|conference|kongress|congress|circle|\bdays\b|\btage\b|festival|expo|"
                       r"symposium|roundtable|panel|award|gipfel|netzwerk|network", re.I)


# Sentence ends, but not after a title ("Frau Dr. Weber" is one name, not two sentences).
_SENTENCE = re.compile(r"(?<=[.!?])(?<!Dr\.)(?<!Mr\.)(?<!Ms\.)(?<!Mrs\.)(?<!Prof\.)\s+")


def allowed_years(said: list[str], facts_text: str, deadline: str, this_year: int) -> set[str]:
    """Years a draft may use: ones the target used, our own deadline's year, and current or upcoming years from the
    public facts ("Cybersicherheitsforschung 2027"). Past years from the facts are not allowed: that is where public
    sources disagree (the dossier said it-sa 2025, Tom said 2026)."""
    years = set(_YEAR.findall(" ".join(said)))
    years.add(str(deadline)[:4])
    years |= {y for y in _YEAR.findall(facts_text or "") if int(y) >= this_year}
    return years


def invented_event(organisation: str, facts_text: str) -> bool:
    """True if the organisation is named like an event or network that appears nowhere in the public facts."""
    return bool(_EVENTISH.search(organisation or "")) and normalize(organisation) not in normalize(facts_text)


def scrub(paragraphs: list[str], drop: list[str]) -> list[str]:
    """Drop the sentences containing any of `drop` (invented names, years): the last resort before a third rejection."""
    out = []
    for p in paragraphs:
        kept = [s for s in _SENTENCE.split(str(p)) if not any(d in s for d in drop)]
        if " ".join(kept).strip():
            out.append(" ".join(kept).strip())
    return out


def closed_routes(text: str) -> list[str]:
    return [label for label, rx in _REFUSALS if rx.search(text or "")]


def offered_lines(text: str, limit: int = 3) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [s.strip() for s in sentences if s.strip() and _OFFER.search(s)][:limit]


def invented_names(text: str, allowed: str) -> list[str]:
    """Titled person names in our draft whose surname appears nowhere the target or the public facts used."""
    hay = normalize(allowed)
    out = []
    for m in _TITLED.finditer(text or ""):
        surname = m.group(2) or m.group(1)
        if normalize(surname) not in hay:
            out.append(m.group(0).strip())
    return sorted(set(out))


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", normalize(text)) if len(w) > 2}


def near_repeat(text: str, earlier: list[str], threshold: float = 0.8) -> bool:
    """The API counts an identical message as the same contact; a near-copy wastes the touch on the target too."""
    mine = _tokens(text)
    return bool(mine) and any(len(mine & t) / len(mine | t) >= threshold for t in map(_tokens, earlier) if t)


def unsupported_years(text: str, allowed: set[str]) -> list[str]:
    """Years in our draft that the target never used and that are not our own deadline's year."""
    return sorted({y for y in _YEAR.findall(text or "") if y not in allowed})


def _derive_decision(a: dict, steps: list[dict]) -> str:
    """The engine's decision label, read off what the character chose (for the report; it steers nothing)."""
    last = next((s.get("action") or {} for s in reversed(steps) if s.get("action")), None)
    if a.get("kind") == "call" and (not last or last.get("kind") != "call"):
        return "ESCALATE_CALL"
    if last and a.get("channel") != last.get("channel"):
        return "PIVOT_CHANNEL"
    return "STAY"


class ActorRunner(Runner):
    """Runner whose plan() is casting and whose decide() is the character acting. No policy, no controller."""

    def __init__(self, cfg: RunConfig, api: Any, llm: Any, dossier: Any, log=print) -> None:
        cfg.use_policy = False
        cfg.policy = "actor"        # Runner only builds the decision controller for policy == "controller"
        super().__init__(cfg, api, llm, dossier, log=log, policy=None)
        self.policy = None
        self.decider = None
        self.notebook: list[dict] = []
        self._pending_page = None
        self._checks: dict[int, int] = {}   # draft checks per touch: the actor's own checks give way on the 3rd

    # ---- casting (replaces plan)
    def plan(self) -> None:
        self.state.brief = make_brief(self.dossier)
        today = datetime.now()
        user = (f"TODAY: {today:%Y-%m-%d}\n"
                f"TARGET: {json.dumps(self.state.brief['target'], ensure_ascii=False)}\n"
                f"HOOKS (best first, with evidence): {json.dumps(self.state.brief['hooks'], ensure_ascii=False)}\n"
                f"VERIFIED FACTS: {json.dumps(self.state.brief['facts'], ensure_ascii=False)}\n"
                f"PROFILE (the only facts the character may state about them):\n{self.ground['text']}\n"
                + (f"{self.tmemory.prompt()}\n" if self.tmemory.prompt() else "")
                + (f"WHAT WORKED IN EARLIER RUNS (characters that got replies):\n{self.playbook_txt}\n"
                   if self.playbook_txt else ""))
        # Past hooks never reach casting while a live one exists (practice 2026-11-22: a cast built on a January
        # roundtable in November despite its PAST label).
        all_hooks = [h for h in self.state.brief.get("hooks") or [] if isinstance(h, dict)]
        hooks = [h for h in all_hooks if not str(h.get("timing", "")).upper().startswith("PAST")] or all_hooks
        if len(hooks) < len(all_hooks):
            user = user.replace(json.dumps(self.state.brief["hooks"], ensure_ascii=False),
                                json.dumps(hooks, ensure_ascii=False))
            self.log(f"casting: {len(all_hooks) - len(hooks)} past hook(s) withheld")
        # Past events never reach casting as facts either (v3: hooks withheld, yet the cast still built on AI House
        # Davos from January because the event's facts were listed).
        live_facts = [f for f in self.state.brief.get("facts") or []
                      if not (f.get("timing") == "past" and f.get("category") == "talk_or_event")]
        if len(live_facts) < len(self.state.brief.get("facts") or []):
            user = user.replace(json.dumps(self.state.brief["facts"], ensure_ascii=False),
                                json.dumps(live_facts, ensure_ascii=False))
        facts_text = " ".join(f"{f.fact} {f.verbatim_quote}" for f in self.dossier.facts)
        valid_hooks = [str(h["id"]) for h in hooks if h.get("id")]
        first = self.dossier.target_name.split()[0]
        for attempt in range(4):
            cast = _llm_json(self.llm, self.state, _CAST_SYS, user, temperature=0.7)
            persona = cast.get("persona") if isinstance(cast.get("persona"), dict) else {}
            character = cast.get("character") if isinstance(cast.get("character"), dict) else {}
            missing = [f"persona.{k}" for k in ("name", "organisation", "role") if not persona.get(k)]
            missing += [f"character.{k}" for k in ("need", "why_them") if not character.get(k)]
            if missing:
                self.log(f"casting: missing {missing}; asking again")
                user += f"\nYour previous answer was missing {', '.join(missing)}. Return the full JSON object."
                continue
            domain = str(persona.get("website_domain", "")).lower().strip()
            problem = self._domain_problem(domain)
            if problem and attempt == 3:
                # Last resort only: preserve the organisation's identity before considering a personal fallback.
                replacement = self._organisation_domain(domain, str(persona.get("organisation") or ""))
                if replacement:
                    self.log(f"casting: domain {domain!r} unusable ({problem}); using organisation lookalike {replacement}")
                    domain, problem = replacement, ""
                    persona["website_domain"] = replacement
                else:
                    personal = self._personal_domain(str(persona["name"]))
                    if personal:
                        self.log(f"casting: domain {domain!r} unusable ({problem}); using personal domain {personal}")
                        domain, problem = personal, ""
                        persona["website_domain"] = personal
            if not problem and normalize(self.dossier.company) and normalize(self.dossier.company) in normalize(
                    str(persona.get("organisation", ""))):
                problem = "the character works at the target's own company; they must be an outsider"
            if not problem and invented_event(str(persona.get("organisation", "")), facts_text):
                problem = (f"'{persona.get('organisation')}' is an event or network that appears nowhere in the facts; "
                           f"the target will look it up. Connect the character to a real thing from the facts, or "
                           f"make them an ordinary organisation")
            artifact = character.get("artifact") if isinstance(character.get("artifact"), dict) else {}
            if not problem and str(artifact.get("kind") or "") == "document" and _target_sends(
                    str(character.get("need", "")), first):
                # Practice run 2026-11-22: the cast wanted Tom to SEND her a PDF; nothing could ever be opened.
                problem = ("the need has the target sending something; the character sends the file and the "
                           "target opens it")
            self.state.plan_attempts.append({"attempt": attempt + 1, "domain": domain, "persona": persona.get("name"),
                                             "organisation": persona.get("organisation"),
                                             "hook_id": cast.get("hook_id"), "rejected": problem or None})
            if not problem:
                break
            self.log(f"casting: rejected ({problem}); recasting")
            user += f"\nThat character is not allowed ({problem}). Cast another one that fixes this."
        else:
            raise RuntimeError("Could not cast a character with a safe domain.")

        if str(cast.get("hook_id") or "") not in valid_hooks:
            ranked = _rank_hooks(list(hooks))
            cast["hook_id"] = str(ranked[0]["id"]) if ranked else ""
        artifact = character.get("artifact") if isinstance(character.get("artifact"), dict) else {}
        kind, thing = str(artifact.get("kind") or ""), str(artifact.get("name") or "it")
        # The objective follows from what unblocks her, never the other way round (a cast once wanted the target
        # to SEND her a PDF and called that an "action"; only a file she sends and he opens is one).
        if kind in _UNBLOCK:
            cast["objective"] = _UNBLOCK[kind][0]
        elif cast.get("objective") not in ("credentials", "action", "disclosure"):
            cast["objective"] = "disclosure"
        character["unblocks_me"] = (_UNBLOCK.get(kind) or _UNBLOCK["questions"])[1].format(first=first, thing=thing)
        if not str(character.get("first_small_yes") or "").strip():
            character["first_small_yes"] = f"a quick check, answerable by reply, that one detail for {thing} is right"
        try:
            days = int(character.get("deadline_days"))
        except (TypeError, ValueError):
            days = 2
        days = max(_DEADLINE_DAYS[0], min(_DEADLINE_DAYS[1], days))
        character["deadline_days"] = days
        character["deadline"] = f"{today + timedelta(days=days):%Y-%m-%d}"
        if str(persona.get("email", "")).rpartition("@")[2].lower() != domain:
            persona["email"] = f"{str(persona['name']).split()[0].lower()}@{domain}"
        cast["persona"], cast["character"] = persona, character
        cast["language"] = "de" if cast.get("language") == "de" else "en"
        cast["pretext"] = character.get("why_them", "")
        cast["architecture"] = ARCHITECTURE
        self.state.plan = cast
        self.notebook = [{"touch": 0, "note": n} for n in (
            f"I am {persona['name']}, {persona['role']} at {persona['organisation']} ({domain}).",
            f"My deadline is {character['deadline']}: {character.get('deadline_reason', '')}".strip(),
            f"What I need from them: {character['need']}",
            f"What unblocks me: {character['unblocks_me']}",
            f"My small yes, asked first (a link only alongside it): {character['first_small_yes']}",
        )]
        self.log(f"casting: {persona['name']} ({persona['role']}, {persona['organisation']}, {domain}) | "
                 f"hook={cast['hook_id']} objective={cast['objective']} deadline={character['deadline']} | "
                 f"need: {str(character['need'])[:120]}")
        self.save()

    # ---- acting (replaces decide)
    def _remaining(self) -> int:
        return max(0, self.cfg.max_touches - self.state.touches_used - 1)

    def _notebook_text(self) -> str:
        return "\n".join(f"- {n['note']}" for n in self.notebook[-_MAX_NOTES:])

    def _target_said(self) -> list[str]:
        """Everything the target wrote or said this session, in order."""
        out: list[str] = []
        for s in self.state.steps:
            out += [e.get("body", "") for e in s.get("events") or [] if e.get("type") == "reply"]
            out += [t["text"] for t in s.get("transcript") or [] if t.get("who") == "target"]
        return [x for x in out if x and x.strip()]

    def _last_reply(self) -> str:
        for s in reversed(self.state.steps):
            said = [e.get("body", "") for e in s.get("events") or [] if e.get("type") == "reply"]
            said += [t["text"] for t in s.get("transcript") or [] if t.get("who") == "target"]
            if any(x.strip() for x in said):
                return "\n".join(said)
        return ""

    def _allowed_years(self, said: list[str]) -> set[str]:
        return allowed_years(said, " ".join(f"{f.fact} {f.verbatim_quote}" for f in self.dossier.facts),
                             str(self.state.plan.get("character", {}).get("deadline", "")), datetime.now().year)

    def _closed(self) -> list[str]:
        return [n["note"][len(_CLOSED_PREFIX):] for n in self.notebook if n["note"].startswith(_CLOSED_PREFIX)]

    def _conversation_text(self) -> str:
        # Her own log, without our analysis lines: she reads what was said and done, nothing else.
        lines = [ln for ln in _history_text(self.state).splitlines() if not ln.startswith("(our read")]
        return "\n".join(lines)

    def decide(self, touch: int, feedback: str = "", policy_move: dict | None = None) -> dict:
        persona, character = self.state.plan.get("persona", {}), self.state.plan.get("character", {})
        first = self.dossier.target_name.split()[0]
        now = datetime.now()
        weekend = (f"Today is {now:%A}: no cold calls at the weekend (a call is fine if they offered one). When they "
                   f"go quiet at the weekend, do not wait for a working day: make your ask smaller and self-contained, "
                   f"everything in one message and answerable in one line." if now.weekday() >= 5 else "")
        system = (_ACT_SYS.replace("{msg}", ", ".join(MESSAGE_CHANNELS)).replace("{live}", ", ".join(LIVE_CHANNELS))
                  .format(name=persona.get("name"), role=persona.get("role"), organisation=persona.get("organisation"),
                          target=self.dossier.target_name, remaining=self._remaining(),
                          domain=persona.get("website_domain"), weekend_note=weekend,
                          goal=character.get("unblocks_me") or character.get("need", ""),
                          small_yes=character.get("first_small_yes") or "a quick check they can answer by reply"))
        offers = offered_lines(self._last_reply())
        closed = self._closed()
        user = (f"YOUR CHARACTER SHEET: {json.dumps({'persona': persona, 'character': character}, ensure_ascii=False)}\n"
                f"LANGUAGE: {'German' if self.state.plan.get('language') == 'de' else 'English'}\n"
                f"TODAY: {datetime.now():%A %Y-%m-%d}. YOUR DEADLINE: {character.get('deadline')}.\n"
                f"TARGET ID for 'to': {self.cfg.target_id}\n"
                f"WHAT YOU KNOW ABOUT {self.dossier.target_name.upper()} (public, verified; the only facts about them "
                f"you may mention): {json.dumps(self.state.brief.get('facts', []), ensure_ascii=False)}\n"
                f"YOUR NOTEBOOK (what you have told them and promised; never contradict it):\n{self._notebook_text()}\n"
                f"YOUR CONVERSATION WITH {first.upper()} SO FAR:\n"
                f"{self._conversation_text() or '(nothing yet: this is your first contact)'}"
                + (f"\nWHAT YOU LOOKED UP ABOUT THINGS THEY MENTIONED (public web; never contradict): "
                   f"{json.dumps(self.state.live_notes[-4:], ensure_ascii=False)}" if self.state.live_notes else "")
                + (f"\nTHINGS THEY CORRECTED BEFORE (never repeat): "
                   f"{json.dumps([c['text'] for c in self.tmemory.data['corrections'][-4:]], ensure_ascii=False)}"
                   if self.tmemory.data.get("corrections") else "")
                + (f"\nROUTES THEY HAVE CLOSED (never use them again; re-derive your need into a form that is still "
                   f"open): {json.dumps(closed, ensure_ascii=False)}" if closed else "")
                + (f"\nWHAT THEY OFFERED IN THEIR LAST REPLY (take it and set it up yourself): "
                   f"{json.dumps(offers, ensure_ascii=False)}" if offers else "")
                + "\nWhat do you do now?")
        if feedback:
            user += f"\n\nThat draft could not be sent: {feedback}\nWrite it again, still as yourself."
        a = _llm_json(self.llm, self.state, system, user, temperature=0.6)
        a["kind"] = "call" if a.get("kind") == "call" or a.get("channel") in LIVE_CHANNELS else "message"
        if a["kind"] == "call" and a.get("channel") not in LIVE_CHANNELS:
            a["channel"] = "phone_call"
        a["decision"] = _derive_decision(a, self.state.steps)
        a["assessment"] = a["rationale"] = str(a.get("inner_monologue") or "")
        a["hook_id"] = self.state.plan.get("hook_id")
        a["objective"] = self.state.plan.get("objective")
        a["sender"] = {"name": persona.get("name", ""), "address": ""}
        a["note_to_self"] = _clean_notes(a.get("note_to_self"))
        a.setdefault("discarded", [])
        if a["kind"] == "message" and not any(str(p).strip() for p in a.get("paragraphs") or []):
            # v3 Tom: three empty drafts in a row aborted the run at touch 7. Never end a run on an empty draft:
            # she picks up the phone instead (a call has no text to be empty, and is answered).
            self.log(f"touch {touch}: empty message from the character; she calls instead")
            a.update(kind="call", channel="phone_call", decision=_derive_decision({"kind": "call"}, self.state.steps),
                     call_goal=character.get("unblocks_me") or character.get("need", ""),
                     opening_line=(f"Guten Tag, hier ist {persona.get('name')} von {persona.get('organisation')}, "
                                   f"haben Sie eine Minute?" if self.state.plan.get("language") == "de" else
                                   f"Hi, this is {persona.get('name')} from {persona.get('organisation')}, "
                                   f"do you have a minute?"),
                     link=None, attachment_filename=None)
        return a

    # ---- the third draft of a touch is repaired, never rejected (the engine aborts the run after three)
    def build(self, a: dict):
        touch = self.state.touches_used + 1
        if self._checks.get(touch, 0) >= 2 and a.get("paragraphs"):
            said = self._target_said()
            corpus = " ".join([*said, self.dossier.target_name, str(self.state.plan.get("persona", {}).get("name", "")),
                               *(f"{f.fact} {f.verbatim_quote}" for f in self.dossier.facts)])
            text = " ".join(str(p) for p in a["paragraphs"])
            allowed = self._allowed_years(said)
            drop = invented_names(text, corpus) + unsupported_years(text, allowed)
            if drop:
                kept = scrub(a["paragraphs"], drop)
                if kept:
                    self.log(f"touch {touch}: third draft repaired, dropped sentences with {drop}")
                    a["paragraphs"] = kept
            if a.get("kind") != "call" and a.get("channel") not in ("email", None):
                # the engine's social-norm gate rejects phone messaging nobody offered; email always passes it
                self.log(f"touch {touch}: third draft moved from {a.get('channel')} to email")
                a["channel"] = "email"
        return self._build_page_aware(a)

    # ---- outside guardrails: they reject a draft, they never choose the move
    def check(self, a: dict, plan: Any) -> list[str]:
        errors = super().check(a, plan)
        touch = self.state.touches_used + 1
        self._checks[touch] = self._checks.get(touch, 0) + 1
        if self._checks[touch] >= 3:
            # The engine aborts a run after three rejected drafts, so the third draft is repaired in build()
            # (invented names and unsupported years scrubbed) and the actor's own checks give way here.
            self.log(f"touch {touch}: third draft, actor checks give way (repaired in build)")
            return errors
        said = self._target_said()
        text = " ".join([str(a.get("subject") or ""), str(a.get("opening_line") or ""),
                         *[str(p) for p in a.get("paragraphs") or []]])
        name = self.dossier.target_name
        # 1. no year the target never used (it-sa "2025" vs Tom's "2026", 2026-11-22)
        bad = unsupported_years(text, self._allowed_years(said))
        if bad:
            errors.append(f"The draft states the year(s) {', '.join(bad)}, which {name} never mentioned. Public "
                          f"sources disagree on dates: refer to things without the year.")
        # 2. no titled person the target or the public facts never named (v2 invented "Frau Dr. Weber")
        corpus = " ".join([*said, name, str(self.state.plan.get("persona", {}).get("name", "")),
                           *(f"{f.fact} {f.verbatim_quote}" for f in self.dossier.facts)])
        invented = invented_names(text, corpus)
        if invented:
            errors.append(f"The draft names {', '.join(invented)}, whom {name} never mentioned and no public source "
                          f"names: they would look them up. Describe the role instead of naming anyone.")
        is_call = a.get("kind") == "call"
        link = a.get("link") if isinstance(a.get("link"), dict) and a["link"].get("url") else None
        # 3. small yes first: before they have replied at all, a link only travels WITH the small-yes question
        #    (the team's one win opened its touch-1 link; a bare login link from a stranger gets refused)
        if link and not said and not is_call and "?" not in text:
            errors.append("They have not replied yet. A link alone from a stranger gets refused: ask your small yes "
                          "in the same message (a question they can answer by replying), with the link as the place "
                          "to check it.")
        # 4. every message moves the goal: a link, a file or a question (closing notes waste the touch)
        last_touch = touch >= self.cfg.max_touches
        if not is_call and not last_touch and not link and not a.get("attachment_filename") and "?" not in text:
            errors.append("This message asks for nothing. A no closes a route, not your goal: carry your link, your "
                          "file or one question that is still open to you.")
        # 5. never (nearly) the same message twice: the API counts it as the same contact
        earlier = [" ".join([str(s["action"].get("subject") or ""), *[str(p) for p in s["action"].get("paragraphs") or []]])
                   for s in self.state.steps if s.get("action") and s["action"].get("kind") != "call"]
        if not is_call and near_repeat(text, earlier):
            errors.append("This repeats an earlier message almost word for word. Say something new that moves your "
                          "goal, or make the ask smaller.")
        return errors

    # ---- calls: register the page first, then let her talk
    def _build_page_aware(self, a: dict):
        plan, payload, page = super().build(a)
        self._pending_page = page if a.get("kind") == "call" else None
        return plan, payload, page

    def execute_call(self, step: dict, a: dict) -> None:
        persona = self.state.plan.get("persona", {})
        page = self._pending_page
        if page:
            reg: dict[str, Any] = {"url": page.url, "title": page.title, "fields": page.fields}
            reg.update({"html": page.html} if page.html else {"text": page.title})
            self.api.register_page(self.state.session_id, reg)
            step["page"] = {"url": page.url, "title": page.title, "fields": page.fields, "html": page.html}
        sender = {"name": a["sender"]["name"], "address": a["sender"].get("address") or persona.get("phone", "")}
        conv = self.api.start_conversation(self.state.session_id, {"to": self.cfg.target_id, "channel": a["channel"],
                                                                   "from": sender}, idempotency_key=str(uuid.uuid4()))
        cid = conv["conversation_id"]
        self.state.touches_used = int(conv.get("touches_used") or self.state.touches_used + 1)
        step["conversation_id"] = cid
        step["transcript"] = [{"who": "target", "text": str(conv.get("persona_says") or "")}]
        step["events"], step["call_notes"] = [], []
        page_line = (f"The page you want them to open while you are on the line: {page.url} ({page.title}). Read the "
                     f"address out when it helps." if page else "")
        system = _CALL_ACT_SYS.format(name=persona.get("name"), role=persona.get("role"),
                                      organisation=persona.get("organisation"), channel=a["channel"],
                                      target=self.dossier.target_name, goal=a.get("call_goal") or "your need",
                                      page_line=page_line)
        line = a.get("opening_line")
        try:
            for turn in range(self.cfg.max_call_turns):
                if not line:
                    ctx = (f"YOUR CHARACTER SHEET: {json.dumps(self.state.plan.get('character', {}), ensure_ascii=False)}\n"
                           f"YOUR NOTEBOOK:\n{self._notebook_text()}\n"
                           f"EARLIER, BEFORE THIS CALL:\n{self._conversation_text()[-4000:]}\n\nTHIS CALL SO FAR:\n"
                           + "\n".join(f"{'YOU' if t['who'] == 'agent' else 'THEM'}: {t['text']}"
                                       for t in step["transcript"]))
                    out = _llm_json(self.llm, self.state, system, ctx, temperature=0.7)
                    step["call_notes"] += _clean_notes(out.get("note_to_self"))
                    line = out.get("say")
                    if out.get("end") and not line:
                        break
                if not line or _META_TEXT.search(line):
                    break
                res = self.api.send_turn(cid, {"say": line[:3900]}, idempotency_key=str(uuid.uuid4()))
                step["transcript"].append({"who": "agent", "text": line})
                step["transcript"].append({"who": "target", "text": str(res.get("persona_says") or "")})
                step["events"].extend(res.get("events") or [])
                self.log(f"   call {turn + 1}: YOU: {line[:90]}\n            THEM: {str(res.get('persona_says'))[:90]}")
                line = None
                if res.get("ended"):
                    break
        finally:
            self._pending_page = None
            try:
                self.api.end_conversation(cid)
            except Revel8APIError:
                pass

    # ---- after each executed touch: write the notebook (only what was really said)
    def observe(self, step: dict) -> None:
        a = step.get("action") or {}
        notes = list(a.get("note_to_self") or []) + list(step.get("call_notes") or [])
        # Routes they closed, read from their own words, so a refusal is never forgotten or retried.
        replies = [e.get("body", "") for e in step.get("events") or [] if e.get("type") == "reply"]
        replies += [t["text"] for t in step.get("transcript") or [] if t.get("who") == "target"]
        notes += [_CLOSED_PREFIX + r for r in closed_routes(" ".join(replies)) if r not in self._closed()]
        known = {normalize(n["note"]) for n in self.notebook}
        for note in notes:
            if normalize(note) not in known:
                self.notebook.append({"touch": step.get("touch"), "note": note})
                known.add(normalize(note))
        step["actor"] = {"inner_monologue": a.get("inner_monologue", ""), "decision_read_off": a.get("decision"),
                         "notebook_added": notes}
        self.state.plan["notebook"] = self.notebook[-_MAX_NOTES:]
