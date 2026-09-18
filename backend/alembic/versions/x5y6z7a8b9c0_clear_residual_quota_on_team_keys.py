"""clear residual quota_usd/monthly_quota_usd on team-owned keys

Team keys are governed entirely by the /teams dashboard: their budget comes from
TeamMember.allocated_usd (a monthly/rollover window), not from the token's own
lifetime quota_usd or monthly_quota_usd. But keys created standalone with a
quota_usd and *later* added to a team kept that lifetime cap, so the /tokens page
showed the lifetime "used / quota_usd" (and could trip "Quota Exceeded" via
quota.py's independent lifetime check) while /teams showed the monthly
allocated_usd window — the two pages diverged.

New members created via /teams already carry no quota_usd. This one-off data
migration backfills the same invariant for existing team keys.

Revision ID: x5y6z7a8b9c0
Revises: w4x5y6z7a8b9
Create Date: 2026-09-18

"""

from alembic import op

revision = "x5y6z7a8b9c0"
down_revision = "w4x5y6z7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Null out any lifetime/monthly quota still attached to a token that is a
    # team member; the team allocation is the single source of truth for them.
    op.execute(
        """
        UPDATE api_tokens
        SET quota_usd = NULL,
            monthly_quota_usd = NULL
        WHERE id IN (SELECT token_id FROM team_members)
          AND (quota_usd IS NOT NULL OR monthly_quota_usd IS NOT NULL)
        """
    )


def downgrade() -> None:
    # Irreversible: the original per-token quota values are not retained.
    pass
