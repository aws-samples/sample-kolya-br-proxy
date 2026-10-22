# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
"""Daily drift check between hardcoded model-card prices and live cards."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.model_card_check import ModelCardPriceCheck
from app.services import model_card_checker as checker
from app.services.pricing import OFFICIAL_PROFILE_PRICING

M = Decimal(1_000_000)
SCOPE_LABELS = {
    "in-region": "Regional ( bedrock-mantle in US East (N. Virginia))",
    "us": "US Geo CRIS",
    "global": "Global CRIS ( bedrock-runtime )",
}


def _cell(value):
    return "—" if value is None else f"${(value * M).normalize()}"


def _card_from_catalog(url, override=None):
    """Render a model card the way AWS does, from the hardcoded catalog."""
    override = override or {}
    tables = {}
    for model_id, pricing in OFFICIAL_PROFILE_PRICING.items():
        if pricing.source_url != url:
            continue
        scope = checker._scope_of(model_id)
        for tier, tier_pricing in checker._expected(model_id):
            bands = [("short", tier_pricing.short)]
            if tier_pricing.long is not None:
                bands.append(("long", tier_pricing.long))
            for band, rates in bands:
                values = [
                    override.get((model_id, tier, band, f), getattr(rates, f))
                    for f in checker.RATE_FIELDS
                ]
                row = (
                    f"<tr><td>{SCOPE_LABELS[scope]}</td>"
                    + "".join(f"<td>{_cell(v)}</td>" for v in values)
                    + "</tr>"
                )
                tables.setdefault(
                    (tier, band, tier_pricing.long_context_threshold), []
                ).append(row)
    out = []
    for (tier, band, threshold), rows in tables.items():
        k = (threshold or 0) // 1000
        size = (
            f"{k}K input tokens or fewer"
            if band == "short"
            else f"more than {k}K input tokens"
        )
        out.append(
            f"<h3>{tier.title()} — Commercial Regions, {band} context ({size})</h3>"
            "<table><thead><tr><th>Inference option</th><th>Input</th>"
            "<th>Input — cache write</th><th>Input — cache read</th><th>Output</th>"
            "</tr></thead>" + "".join(rows) + "</table>"
        )
    return "<html>" + "".join(out) + "</html>"


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(ModelCardPriceCheck.__table__.create)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def test_parses_real_card_layouts():
    page = """
    <h3>Standard — Commercial Regions, short context (272K input tokens or fewer)</h3>
    <table><thead><tr><th><b>Inference option</b></th><th><b>Input</b></th>
    <th><b>Input — 30-minute cache write</b></th><th><b>Input — cache read</b></th>
    <th><b>Output</b></th></tr></thead>
    <tr><td>In-Region ( bedrock-mantle in us-east-1 )</td><td>$2.20</td><td>$2.75</td><td>$0.11</td><td>$11.00</td></tr>
    <tr><td>Geo CRIS (US)</td><td>$2.20</td><td>$2.75</td><td>$0.11</td><td>$11.00</td></tr>
    <tr><td>Global CRIS</td><td>$2.00</td><td>—</td><td>$0.10</td><td>$10.00</td></tr></table>
    <p><b>AWS GovCloud (US-West) — short context (272K input tokens or fewer)</b></p>
    <table><tr><th>Inference option</th><th>Input</th><th>Output</th></tr>
    <tr><td>In-Region</td><td>$9.99</td><td>$9.99</td></tr></table>
    <table><caption>Ultrafast — Commercial Regions, long context (more than 272K input tokens)</caption>
    <tr><th>Inference option</th><th>Input</th><th>Output</th><th>Cache read</th></tr>
    <tr><td>Global CRIS</td><td>$24.00</td><td>$90.00</td><td>$1.20</td></tr></table>
    """
    card = checker.parse_model_card(page)

    assert (
        card.rates[("standard", "short", "in-region")]["input"] == Decimal("2.20") / M
    )
    assert card.rates[("standard", "short", "us")]["cache_write"] == Decimal("2.75") / M
    # "—" = not published, so it is never compared.
    assert card.rates[("standard", "short", "global")]["cache_write"] is None
    assert (
        card.rates[("ultrafast", "long", "global")]["cache_read"] == Decimal("1.20") / M
    )
    assert card.thresholds[("ultrafast", "long")] == 272_000
    # GovCloud prices never override commercial ones.
    assert card.rates[("standard", "short", "in-region")]["output"] == Decimal("11") / M


def test_every_catalogued_card_round_trips_without_issues():
    for model_id, pricing in OFFICIAL_PROFILE_PRICING.items():
        card = checker.parse_model_card(_card_from_catalog(pricing.source_url))
        assert checker.compare_model(model_id, card) == [], model_id


def test_reports_price_threshold_and_tier_drift():
    model = "global.openai.gpt-6.1-sol"
    url = OFFICIAL_PROFILE_PRICING[model].source_url
    page = _card_from_catalog(
        url, {(model, "standard", "short", "input"): Decimal("2.40") / M}
    ).replace("more than 272K", "more than 300K", 1)
    issues = checker.compare_model(model, checker.parse_model_card(page))

    assert "standard short-context global input: catalog $2, card $2.4" in issues
    assert "standard long-context threshold: catalog 272000, card 300000" in issues

    empty = checker.compare_model(model, checker.ParsedCard())
    assert "standard short-context global: not found on card" in empty


@pytest.mark.asyncio
async def test_notifies_only_when_drift_appears_or_changes(db):
    drifted = "global.openai.gpt-6-sol"
    drift_url = OFFICIAL_PROFILE_PRICING[drifted].source_url
    price = {"value": Decimal("2.10") / M}

    async def fetch(url):
        if url == drift_url:
            return _card_from_catalog(
                url, {(drifted, "standard", "short", "input"): price["value"]}
            )
        return _card_from_catalog(url)

    with patch.object(checker, "_notify", AsyncMock()) as notify:
        stats = await checker.check_model_cards(db, fetch=fetch)
        assert stats["checked"] == len(OFFICIAL_PROFILE_PRICING)
        assert notify.await_count == 1
        [(_, changed)] = [c.args for c in notify.await_args_list]
        assert [m for m, _, _ in changed] == [drifted]

        # Same drift next day: recorded, not re-notified.
        await checker.check_model_cards(db, fetch=fetch)
        assert notify.await_count == 1

        # Different drift: notify again.
        price["value"] = Decimal("2.30") / M
        await checker.check_model_cards(db, fetch=fetch)
        assert notify.await_count == 2

        # Catalog updated / card reverted: resolved silently.
        price["value"] = OFFICIAL_PROFILE_PRICING[drifted].short.input
        await checker.check_model_cards(db, fetch=fetch)
        assert notify.await_count == 2

    rows = {
        r.model_id: r for r in (await db.execute(select(ModelCardPriceCheck))).scalars()
    }
    assert set(rows) == set(OFFICIAL_PROFILE_PRICING)
    assert {r.status for r in rows.values()} == {"ok"}


@pytest.mark.asyncio
async def test_unreachable_card_is_reported_as_parse_error(db):
    async def fetch(url):
        raise RuntimeError("503")

    with patch.object(checker, "_notify", AsyncMock()) as notify:
        stats = await checker.check_model_cards(db, fetch=fetch)

    assert stats["drift"] == len(OFFICIAL_PROFILE_PRICING)
    [(_, changed)] = [c.args for c in notify.await_args_list]
    assert {status for _, status, _ in changed} == {"parse_error"}


def test_message_lists_models_and_points_at_the_catalog():
    message = checker._message(
        [("global.openai.gpt-6-sol", "mismatch", ["a", "b", "c", "d", "e"])]
    )
    assert "Billing still uses the hardcoded rates" in message
    assert "global.openai.gpt-6-sol (mismatch): a; b; c" in message
    assert "and 2 more" in message


@pytest.mark.asyncio
async def test_notify_reaches_super_admins_and_optional_email():
    import uuid as uuid_mod
    from unittest.mock import MagicMock

    admins = [uuid_mod.uuid4(), uuid_mod.uuid4()]
    result = MagicMock()
    result.scalars.return_value = iter(admins)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    changed = [("global.openai.gpt-6-sol", "mismatch", ["x"])]

    with (
        patch(
            "app.core.config.get_settings",
            return_value=MagicMock(MODEL_CARD_DRIFT_NOTIFY_EMAIL="ops@example.com"),
        ),
        patch("app.services.notification.dispatch_alert") as dispatch,
    ):
        await checker._notify(session, changed)

    added = [c.args[0] for c in session.add.call_args_list]
    assert [n.user_id for n in added] == admins
    assert {n.scope_type for n in added} == {"system"}
    assert {n.rule_key for n in added} == {"model_card_drift"}
    dispatch.assert_called_once()
    assert dispatch.call_args.args[1] == "ops@example.com"
