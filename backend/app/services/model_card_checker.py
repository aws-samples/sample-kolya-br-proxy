# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
"""Daily drift check between hardcoded model-card prices and the live cards.

Billing for GPT routes and other catalogued profiles uses rates hardcoded from
AWS model cards (``OFFICIAL_PROFILE_PRICING``). This job re-reads every card,
compares each published rate with the hardcoded one and records the result.
It never changes billing: a mismatch or an unparseable card notifies super
admins so a human can update the catalog.
"""

import asyncio
import html as html_lib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import AlertNotification
from app.models.model_card_check import ModelCardPriceCheck
from app.models.user import User, UserRole
from app.services.openai_gpt_catalog import resolve_gpt_route
from app.services.pricing import OFFICIAL_PROFILE_PRICING
from app.services.pricing_types import OfficialProfilePricing, TokenRates

logger = logging.getLogger(__name__)

RATE_FIELDS = ("input", "cache_write", "cache_read", "output")
_ONE_MILLION = Decimal(1_000_000)
# Arbitrary constant: one daily run across all pods.
_ADVISORY_LOCK_KEY = 0x6B62_7063_6172_6473

# (service tier, context band, scope) — e.g. ("standard", "long", "global")
CardKey = Tuple[str, str, str]
Fetcher = Callable[[str], Awaitable[str]]


@dataclass
class ParsedCard:
    rates: Dict[CardKey, Dict[str, Optional[Decimal]]] = field(default_factory=dict)
    # (service tier, band) → token threshold stated in the table caption
    thresholds: Dict[Tuple[str, str], int] = field(default_factory=dict)


def _text(fragment: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html_lib.unescape(plain)).strip()


def _scope(label: str) -> Optional[str]:
    label = label.lower()
    if "global" in label:
        return "global"
    if "us cris" in label or "geo" in label:
        return "us"
    if "in-region" in label or "regional" in label or "mantle" in label:
        return "in-region"
    return None


def _column(header: str) -> Optional[str]:
    header = header.lower()
    if "cache write" in header:
        return "cache_write"
    if "cache read" in header:
        return "cache_read"
    if header.startswith("output"):
        return "output"
    if header == "input":
        return "input"
    return None


def _price(cell: str) -> Optional[Decimal]:
    match = re.fullmatch(r"\$\s*([\d.]+)", cell.strip())
    if not match:
        return None  # "—": not published for this dimension
    try:
        return Decimal(match.group(1)) / _ONE_MILLION
    except InvalidOperation:
        return None


def _caption(table: str, preceding: str) -> str:
    """Table <caption>, else the last heading between the previous table and
    this one (cards title price tables with an <h3>/<h4> or a bold <p>)."""
    caption_m = re.search(r"<caption[^>]*>(.*?)</caption>", table, re.S | re.I)
    if caption_m:
        return _text(caption_m.group(1)).lower()
    headings = re.findall(
        r"<(h[2-6])[^>]*>(.*?)</\1>|<p>\s*<b>(.*?)</b>\s*</p>", preceding, re.S | re.I
    )
    if not headings:
        return ""
    _, heading, bold = headings[-1]
    return _text(heading or bold).lower()


def parse_model_card(page: str) -> ParsedCard:
    """Extract per-token rates from every captioned price table on a card."""
    parsed = ParsedCard()
    previous_end = 0
    for match in re.finditer(r"<table\b.*?</table>", page, re.S | re.I):
        table = match.group()
        caption = _caption(table, page[previous_end : match.start()])
        previous_end = match.end()
        if "$" not in table or "govcloud" in caption:
            continue
        tier = "ultrafast" if "ultrafast" in caption else "standard"
        band = "long" if "long context" in caption else "short"
        threshold_m = re.search(r"(\d+)\s*k input tokens", caption)
        if threshold_m:
            parsed.thresholds[(tier, band)] = int(threshold_m.group(1)) * 1000

        rows = [
            [
                _text(c)
                for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", row, re.S | re.I)
            ]
            for row in re.findall(r"<tr\b.*?</tr>", table, re.S | re.I)
        ]
        if not rows:
            continue
        columns = [_column(h) for h in rows[0]]
        if "input" not in columns or "output" not in columns:
            continue
        for cells in rows[1:]:
            scope = _scope(cells[0]) if cells else None
            if scope is None or len(cells) != len(columns):
                continue
            rates: Dict[str, Optional[Decimal]] = {f: None for f in RATE_FIELDS}
            for kind, cell in zip(columns, cells):
                if kind:
                    rates[kind] = _price(cell)
            parsed.rates.setdefault((tier, band, scope), rates)
    return parsed


def _expected(
    model_id: str,
) -> List[Tuple[str, OfficialProfilePricing]]:
    """(service tier, pricing) pairs the catalog bills for *model_id*."""
    route = resolve_gpt_route(model_id)
    if route is None:
        return [("standard", OFFICIAL_PROFILE_PRICING[model_id])]
    tiers = [("standard", route.pricing)]
    if route.ultrafast_pricing is not None:
        tiers.append(("ultrafast", route.ultrafast_pricing))
    return tiers


def _scope_of(model_id: str) -> str:
    route = resolve_gpt_route(model_id)
    if route is not None:
        return route.scope
    if model_id.startswith("global."):
        return "global"
    if model_id.startswith("us."):
        return "us"
    return "in-region"


def _fmt(value: Optional[Decimal]) -> str:
    return "none" if value is None else f"${(value * _ONE_MILLION).normalize()}"


def compare_model(model_id: str, card: ParsedCard) -> List[str]:
    """Human-readable differences between the catalog and the card."""
    scope = _scope_of(model_id)
    issues: List[str] = []
    expected_tiers = _expected(model_id)
    for tier, pricing in expected_tiers:
        bands: List[Tuple[str, TokenRates]] = [("short", pricing.short)]
        if pricing.long is not None:
            bands.append(("long", pricing.long))
        for band, rates in bands:
            published = card.rates.get((tier, band, scope))
            if published is None:
                issues.append(f"{tier} {band}-context {scope}: not found on card")
                continue
            for name in RATE_FIELDS:
                card_value = published[name]
                if card_value is None:
                    continue
                ours = getattr(rates, name)
                if ours != card_value:
                    issues.append(
                        f"{tier} {band}-context {scope} {name}: "
                        f"catalog {_fmt(ours)}, card {_fmt(card_value)}"
                    )
        threshold = card.thresholds.get((tier, "long"))
        if (
            pricing.long is not None
            and threshold is not None
            and threshold != pricing.long_context_threshold
        ):
            issues.append(
                f"{tier} long-context threshold: catalog "
                f"{pricing.long_context_threshold}, card {threshold}"
            )
        if pricing.long is None and (tier, "long", scope) in card.rates:
            issues.append(f"{tier} {scope}: card adds a long-context band")
    billed_tiers = {tier for tier, _ in expected_tiers}
    if "ultrafast" not in billed_tiers and ("ultrafast", "short", scope) in card.rates:
        issues.append(f"ultrafast {scope}: card lists a tier the catalog does not bill")
    return issues


async def _fetch(url: str) -> str:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


async def _acquire_run_lock(db: AsyncSession) -> bool:
    """Transaction-scoped lock so only one pod runs (and notifies) per day."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return True
    result = await db.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY}
    )
    return bool(result.scalar())


async def check_model_cards(
    db: AsyncSession, fetch: Optional[Fetcher] = None
) -> Dict[str, int]:
    """Check every hardcoded model-card price; notify on new or changed drift."""
    fetch = fetch or _fetch
    if not await _acquire_run_lock(db):
        logger.info("Model-card price check already running on another pod")
        return {"checked": 0, "ok": 0, "drift": 0, "skipped": 1}

    by_url: Dict[str, List[str]] = {}
    for model_id, pricing in OFFICIAL_PROFILE_PRICING.items():
        by_url.setdefault(pricing.source_url, []).append(model_id)

    existing = {
        row.model_id: row
        for row in (await db.execute(select(ModelCardPriceCheck))).scalars()
    }
    now = datetime.utcnow()
    stats = {"checked": 0, "ok": 0, "drift": 0, "skipped": 0}
    changed: List[Tuple[str, str, List[str]]] = []

    for url, model_ids in by_url.items():
        try:
            card: Optional[ParsedCard] = parse_model_card(await fetch(url))
            if not card.rates:
                card = None
        except Exception as e:  # network/HTTP errors are reported, not raised
            logger.warning(f"Model card fetch failed for {url}: {e}")
            card = None

        for model_id in sorted(model_ids):
            if card is None:
                status, issues = "parse_error", [f"could not read prices from {url}"]
            else:
                issues = compare_model(model_id, card)
                status = "mismatch" if issues else "ok"
            stats["checked"] += 1
            stats["ok" if status == "ok" else "drift"] += 1

            row = existing.get(model_id)
            if row is None:
                row = ModelCardPriceCheck(model_id=model_id, changed_at=now)
                db.add(row)
                is_change = status != "ok"
            else:
                is_change = (row.status, row.issues) != (status, issues)
                if is_change:
                    row.changed_at = now
            row.source_url = url
            row.status = status
            row.issues = issues
            row.checked_at = now
            if is_change and status != "ok":
                changed.append((model_id, status, issues))

    for model_id in set(existing) - set(OFFICIAL_PROFILE_PRICING):
        await db.delete(existing[model_id])

    if changed:
        await _notify(db, changed)
    await db.commit()
    logger.info(f"Model-card price check: {stats}")
    return stats


def _message(changed: List[Tuple[str, str, List[str]]]) -> str:
    lines = [
        f"Hardcoded model-card prices differ from AWS for {len(changed)} "
        "model(s). Billing still uses the hardcoded rates; update "
        "openai_gpt_catalog.py / pricing.py after checking the card."
    ]
    for model_id, status, issues in changed:
        lines.append(f"- {model_id} ({status}): " + "; ".join(issues[:3]))
        if len(issues) > 3:
            lines.append(f"  … and {len(issues) - 3} more")
    return "\n".join(lines)


async def _notify(db: AsyncSession, changed: List[Tuple[str, str, List[str]]]) -> None:
    from app.core.config import get_settings
    from app.services.notification import dispatch_alert

    message = _message(changed)
    logger.warning(message)
    issue_count = sum(len(issues) for _, _, issues in changed)
    admins = (
        await db.execute(
            select(User.id).where(
                User.role == UserRole.SUPER_ADMIN, User.is_active.is_(True)
            )
        )
    ).scalars()
    for admin_id in admins:
        db.add(
            AlertNotification(
                id=uuid.uuid4(),
                user_id=admin_id,
                rule_key="model_card_drift",
                alert_type="soft",
                scope_type="system",
                scope_name="Model-card pricing",
                current_value=issue_count,
                threshold_value=0,
                message=message,
                channels_used="in_app",
            )
        )

    recipients = get_settings().MODEL_CARD_DRIFT_NOTIFY_EMAIL
    if recipients:
        try:
            await asyncio.to_thread(dispatch_alert, message, recipients)
        except Exception:
            logger.warning("Failed to email model-card drift alert", exc_info=True)
