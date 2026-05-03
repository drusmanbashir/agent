
# agent/revalidation/triage.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TriageResult = Literal["include", "exclude", "needs_review"]


# Strong signals (journal-agnostic)
INCLUDED_SUBJECT_KEYWORDS: set[str] = {
    # CPD / education
    "cpd",
    "course",
    "webinar",
    "workshop",
    "conference",
    "symposium",
    "training",
    "attendance",
    "certificate",
    "cme",

    # peer review
    "reviewer invitation",
    "review invitation",
    "thank you for reviewing",
    "review completed",
    "peer review",
    "reviewer report",

    # publication lifecycle (critical)
    "publishing agreement",
    "license to publish",
    "licence to publish",
    "copyright transfer",
    "article accepted",
    "accepted for publication",
    "editorial decision",
    "proof",
    "proofs",
    "doi",
    "in press",
    "publication",
    "article status",

    # funding / grants
    "grant",
    "funding decision",
    "award",
    "successful application",
    "unsuccessful application",
    "shortlisted",
}

# Domain signals (keep small; subject keywords cover new journals)
INCLUDED_DOMAINS: set[str] = {
    "elsevier.com",
    "editorialmanager.com",
    "manuscriptcentral.com",      # ScholarOne
    "springernature.com",
    "springer.com",
    "wiley.com",
    "tandf.co.uk",
    "bmj.com",
    "oup.com",
    "oxfordjournals.org",
    "nature.com",
    "thelancet.com",
    "nejm.org",
    "jama-network.com",
    "mdpi.com",
    "frontiersin.org",
}

# Hard exclusions: very likely non-CPD / non-evidence
EXCLUDED_DOMAINS: set[str] = {
    "deliveroo.com",
    "linkedin.com",
    "parentmail.co.uk",
    "uniqlo.eu",
    "johnlewis.com",
    "paypal.com",
    "gilt.com",
    "bulk.com",
    "adobe.com",
    "opentable.co.uk",
    "uber.com",
    "google.com",
    "octopus.energy",
    "hyperoptic.com",
}

EXCLUDED_SUBJECT_KEYWORDS: set[str] = {
    # commerce / marketing
    "sale",
    "discount",
    "off",
    "offer",
    "newsletter",
    "your order",
    "receipt",
    "invoice",
    "reservation",
    "booking confirmation",
    "delivered",
    "delivery",
    "shipping",
    "bill is ready",
    "statement",
    "promo",
    "promotion",

    # account/admin noise
    "security alert",
    "password",
    "reset",
    "verify",
    "otp",
    "code",
}


@dataclass(frozen=True)
class TriageMatch:
    verdict: TriageResult
    reason: str


def _contains_any(text: str, keywords: set[str]) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(k in t for k in keywords)


def _sender_domain(sender: str) -> str:
    """
    Extract simple domain token from typical From header values.
    Examples:
      'Article_Status@elsevier.com' -> 'elsevier.com'
      'Deliveroo <noreply@t.deliveroo.com>' -> 't.deliveroo.com'
    """
    s = (sender or "").lower()
    if "<" in s and ">" in s:
        s = s.split("<", 1)[1].split(">", 1)[0]
    if "@" in s:
        return s.split("@", 1)[1].strip()
    return ""


def _domain_hits(domain: str, domains: set[str]) -> bool:
    if not domain:
        return False
    # allow subdomains to match base domain tokens
    return any(domain == d or domain.endswith("." + d) for d in domains)


def is_included(sender: str, subject: str) -> bool:
    dom = _sender_domain(sender)
    return _domain_hits(dom, INCLUDED_DOMAINS) or _contains_any(subject, INCLUDED_SUBJECT_KEYWORDS)


def is_excluded(sender: str, subject: str) -> bool:
    dom = _sender_domain(sender)
    return _domain_hits(dom, EXCLUDED_DOMAINS) or _contains_any(subject, EXCLUDED_SUBJECT_KEYWORDS)


def triage(sender: str, subject: str) -> TriageMatch:
    """
    Order matters:
      - strong include wins even if subject contains 'newsletter' etc.
      - then apply exclusions
      - otherwise needs_review
    """
    if is_included(sender, subject):
        return TriageMatch("include", "matched include keyword/domain")
    if is_excluded(sender, subject):
        return TriageMatch("exclude", "matched exclusion keyword/domain")
    return TriageMatch("needs_review", "no strong signals either way")


def classify_bucket(sender: str, subject: str) -> str:
    """
    Optional coarse bucket label for included/needs_review items.
    """
    s = (subject or "").lower()
    if _contains_any(s, {"reviewer invitation", "review invitation", "peer review", "review completed"}):
        return "peer_review"
    if _contains_any(s, {"publishing agreement", "license to publish", "licence to publish", "proof", "proofs", "doi", "accepted", "editorial decision", "article status"}):
        return "publication"
    if _contains_any(s, {"grant", "funding decision", "award", "successful application", "unsuccessful application", "shortlisted"}):
        return "funding"
    if _contains_any(s, {"cpd", "course", "webinar", "workshop", "conference", "symposium", "training", "certificate", "cme"}):
        return "cpd"
    return "other"
