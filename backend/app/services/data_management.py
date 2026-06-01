"""
Data management service for export/import of application configuration.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_token, generate_api_token, hash_token
from app.models.alert import AlertRule
from app.models.entra_group_mapping import EntraGroupMapping
from app.models.model import Model
from app.models.team import Team, TeamMember
from app.models.token import APIToken
from app.models.user import AuthMethod, User, UserRole

logger = logging.getLogger(__name__)

EXPORT_VERSION = "1.0"


class SectionResult:
    def __init__(self):
        self.created = 0
        self.skipped = 0
        self.overwritten = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict:
        return {
            "created": self.created,
            "skipped": self.skipped,
            "overwritten": self.overwritten,
            "errors": self.errors,
        }


class DataManagementService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def export_config(self, exported_by: str) -> dict:
        """Export all application configuration as a JSON-serializable dict."""
        return {
            "version": EXPORT_VERSION,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "exported_by": exported_by,
            "sections": {
                "users": await self._export_users(),
                "teams": await self._export_teams(),
                "tokens": await self._export_tokens(),
                "team_members": await self._export_team_members(),
                "alert_rules": await self._export_alert_rules(),
                "entra_group_mappings": await self._export_entra_group_mappings(),
            },
        }

    async def import_config(self, data: dict, conflict_strategy: str) -> dict[str, Any]:
        """
        Import configuration from a JSON dict.
        Returns result summary with generated token keys.
        """
        sections = data.get("sections", {})

        results: dict[str, Any] = {}
        results["users"] = (
            await self._import_users(sections.get("users", []), conflict_strategy)
        ).to_dict()
        results["teams"] = (
            await self._import_teams(sections.get("teams", []), conflict_strategy)
        ).to_dict()

        token_result, generated_keys = await self._import_tokens(
            sections.get("tokens", []), conflict_strategy
        )
        token_dict = token_result.to_dict()
        token_dict["generated_keys"] = generated_keys
        results["tokens"] = token_dict

        results["team_members"] = (
            await self._import_team_members(
                sections.get("team_members", []), conflict_strategy
            )
        ).to_dict()
        results["alert_rules"] = (
            await self._import_alert_rules(
                sections.get("alert_rules", []), conflict_strategy
            )
        ).to_dict()
        results["entra_group_mappings"] = (
            await self._import_entra_group_mappings(
                sections.get("entra_group_mappings", []), conflict_strategy
            )
        ).to_dict()

        await self.db.commit()
        return results

    # ─── Export helpers ─────────────────────────────────────────────

    async def _export_users(self) -> list[dict]:
        result = await self.db.execute(select(User).where(User.is_active.is_(True)))
        users = result.scalars().all()
        return [
            {
                "email": u.email,
                "role": u.role.value if u.role else None,
                "permissions": u.permissions,
                "is_active": u.is_active,
                "is_admin": u.is_admin,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "auth_method": u.auth_method.value if u.auth_method else None,
            }
            for u in users
        ]

    async def _export_teams(self) -> list[dict]:
        result = await self.db.execute(select(Team).where(Team.is_active.is_(True)))
        teams = result.scalars().all()
        return [
            {
                "name": t.name,
                "monthly_budget_usd": str(t.monthly_budget_usd)
                if t.monthly_budget_usd
                else None,
                "monthly_reset_policy": t.monthly_reset_policy,
                "daily_limit_enabled": t.daily_limit_enabled,
            }
            for t in teams
        ]

    async def _export_tokens(self) -> list[dict]:
        result = await self.db.execute(
            select(APIToken).where(
                APIToken.is_deleted.is_(False), APIToken.is_active.is_(True)
            )
        )
        tokens = result.scalars().all()

        exported = []
        for t in tokens:
            # Get user email
            user_result = await self.db.execute(
                select(User.email).where(User.id == t.user_id)
            )
            user_email = user_result.scalar_one_or_none()

            # Get allowed models
            models_result = await self.db.execute(
                select(Model.model_name).where(
                    Model.token_id == t.id,
                    Model.is_active.is_(True),
                    Model.is_deleted.is_(False),
                )
            )
            model_names = list(models_result.scalars().all())

            exported.append(
                {
                    "name": t.name,
                    "user_email": user_email,
                    "quota_usd": str(t.quota_usd) if t.quota_usd else None,
                    "monthly_quota_usd": str(t.monthly_quota_usd)
                    if t.monthly_quota_usd
                    else None,
                    "monthly_reset_policy": t.monthly_reset_policy,
                    "allowed_ips": t.allowed_ips or [],
                    "notify_emails": t.notify_emails or [],
                    "is_active": t.is_active,
                    "token_metadata": t.token_metadata,
                    "allowed_models": model_names,
                }
            )
        return exported

    async def _export_team_members(self) -> list[dict]:
        result = await self.db.execute(
            select(TeamMember, Team.name, APIToken.name, User.email)
            .join(Team, TeamMember.team_id == Team.id)
            .join(APIToken, TeamMember.token_id == APIToken.id)
            .join(User, APIToken.user_id == User.id)
            .where(Team.is_active.is_(True))
        )
        rows = result.all()
        return [
            {
                "team_name": team_name,
                "token_name": token_name,
                "token_user_email": user_email,
                "allocated_usd": str(tm.allocated_usd) if tm.allocated_usd else None,
            }
            for tm, team_name, token_name, user_email in rows
        ]

    async def _export_alert_rules(self) -> list[dict]:
        result = await self.db.execute(
            select(AlertRule).where(AlertRule.is_active.is_(True))
        )
        rules = result.scalars().all()

        exported = []
        for r in rules:
            # Resolve user email
            user_result = await self.db.execute(
                select(User.email).where(User.id == r.user_id)
            )
            user_email = user_result.scalar_one_or_none()

            # Resolve token name + user email if token_id set
            token_name = None
            token_user_email = None
            if r.token_id:
                tok_result = await self.db.execute(
                    select(APIToken.name, User.email)
                    .join(User, APIToken.user_id == User.id)
                    .where(APIToken.id == r.token_id)
                )
                row = tok_result.first()
                if row:
                    token_name, token_user_email = row

            # Resolve team name if team_id set
            team_name = None
            if r.team_id:
                team_result = await self.db.execute(
                    select(Team.name).where(Team.id == r.team_id)
                )
                team_name = team_result.scalar_one_or_none()

            exported.append(
                {
                    "user_email": user_email,
                    "alert_type": r.alert_type,
                    "rule_key": r.rule_key,
                    "threshold_value": str(r.threshold_value)
                    if r.threshold_value
                    else None,
                    "cooldown_hours": r.cooldown_hours,
                    "notify_email": r.notify_email,
                    "notify_in_app": r.notify_in_app,
                    "token_name": token_name,
                    "token_user_email": token_user_email,
                    "team_name": team_name,
                }
            )
        return exported

    async def _export_entra_group_mappings(self) -> list[dict]:
        result = await self.db.execute(select(EntraGroupMapping))
        mappings = result.scalars().all()
        return [
            {
                "entra_group_id": m.entra_group_id,
                "group_name": m.group_name,
                "role": m.role.value if m.role else None,
                "permissions": m.permissions,
                "priority": m.priority,
            }
            for m in mappings
        ]

    # ─── Import helpers ─────────────────────────────────────────────

    async def _resolve_user_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def _import_users(
        self, users_data: list[dict], strategy: str
    ) -> SectionResult:
        sr = SectionResult()
        for item in users_data:
            email = item.get("email")
            if not email:
                sr.errors.append("User entry missing email")
                continue

            existing = await self._resolve_user_by_email(email)
            if existing:
                if strategy == "skip":
                    sr.skipped += 1
                else:
                    existing.role = (
                        UserRole(item["role"]) if item.get("role") else existing.role
                    )
                    existing.permissions = item.get("permissions", existing.permissions)
                    existing.is_active = item.get("is_active", existing.is_active)
                    if "is_admin" in item:
                        existing.is_admin = item["is_admin"]
                    existing.first_name = item.get("first_name", existing.first_name)
                    existing.last_name = item.get("last_name", existing.last_name)
                    if item.get("auth_method"):
                        existing.auth_method = AuthMethod(item["auth_method"])
                    sr.overwritten += 1
            else:
                role = UserRole(item["role"]) if item.get("role") else UserRole.ADMIN
                user = User(
                    email=email,
                    role=role,
                    permissions=item.get("permissions"),
                    is_active=item.get("is_active", True),
                    # Preserve the source's admin flag; fall back to deriving it
                    # from role (every role here is an admin tier) — never elevate.
                    is_admin=item.get(
                        "is_admin", role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)
                    ),
                    first_name=item.get("first_name"),
                    last_name=item.get("last_name"),
                    auth_method=AuthMethod(item["auth_method"])
                    if item.get("auth_method")
                    else AuthMethod.COGNITO,
                    email_verified=False,
                )
                self.db.add(user)
                sr.created += 1

        await self.db.flush()
        return sr

    async def _import_teams(
        self, teams_data: list[dict], strategy: str
    ) -> SectionResult:
        sr = SectionResult()
        for item in teams_data:
            name = item.get("name")
            if not name:
                sr.errors.append("Team entry missing name")
                continue

            result = await self.db.execute(
                select(Team).where(Team.name == name, Team.is_active.is_(True))
            )
            existing = result.scalar_one_or_none()

            if existing:
                if strategy == "skip":
                    sr.skipped += 1
                else:
                    if item.get("monthly_budget_usd"):
                        existing.monthly_budget_usd = Decimal(
                            item["monthly_budget_usd"]
                        )
                    existing.monthly_reset_policy = item.get(
                        "monthly_reset_policy", existing.monthly_reset_policy
                    )
                    existing.daily_limit_enabled = item.get(
                        "daily_limit_enabled", existing.daily_limit_enabled
                    )
                    sr.overwritten += 1
            else:
                # Find a super-admin to be the team owner
                admin_result = await self.db.execute(
                    select(User).where(User.role == UserRole.SUPER_ADMIN).limit(1)
                )
                owner = admin_result.scalar_one_or_none()
                if not owner:
                    sr.errors.append(f"Team '{name}': no super-admin found to be owner")
                    continue

                team = Team(
                    name=name,
                    user_id=owner.id,
                    monthly_budget_usd=Decimal(item["monthly_budget_usd"])
                    if item.get("monthly_budget_usd")
                    else None,
                    monthly_reset_policy=item.get("monthly_reset_policy"),
                    daily_limit_enabled=item.get("daily_limit_enabled", False),
                    monthly_budget_start=datetime.utcnow(),
                    is_active=True,
                )
                self.db.add(team)
                sr.created += 1

        await self.db.flush()
        return sr

    async def _import_tokens(
        self, tokens_data: list[dict], strategy: str
    ) -> tuple[SectionResult, list[dict]]:
        sr = SectionResult()
        generated_keys: list[dict] = []

        for item in tokens_data:
            name = item.get("name")
            user_email = item.get("user_email")
            if not name or not user_email:
                sr.errors.append(f"Token entry missing name or user_email: {name}")
                continue

            user = await self._resolve_user_by_email(user_email)
            if not user:
                sr.errors.append(f"Token '{name}': user '{user_email}' not found")
                continue

            result = await self.db.execute(
                select(APIToken).where(
                    APIToken.name == name,
                    APIToken.user_id == user.id,
                    APIToken.is_deleted.is_(False),
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                if strategy == "skip":
                    sr.skipped += 1
                else:
                    if item.get("quota_usd"):
                        existing.quota_usd = Decimal(item["quota_usd"])
                    if item.get("monthly_quota_usd"):
                        existing.monthly_quota_usd = Decimal(item["monthly_quota_usd"])
                    existing.monthly_reset_policy = item.get(
                        "monthly_reset_policy", existing.monthly_reset_policy
                    )
                    if "allowed_ips" in item:
                        existing.allowed_ips = item["allowed_ips"]
                    if "notify_emails" in item:
                        existing.notify_emails = item["notify_emails"]
                    if "token_metadata" in item:
                        existing.token_metadata = item["token_metadata"]
                    if "is_active" in item:
                        existing.is_active = item["is_active"]
                    # Sync allowed_models
                    if "allowed_models" in item:
                        await self._sync_token_models(
                            existing.id, item["allowed_models"]
                        )
                    sr.overwritten += 1
            else:
                # Generate new token
                plain_token = generate_api_token()
                token_hash = hash_token(plain_token)
                encrypted = encrypt_token(plain_token)

                token = APIToken(
                    user_id=user.id,
                    name=name,
                    token_hash=token_hash,
                    encrypted_token=encrypted,
                    quota_usd=Decimal(item["quota_usd"])
                    if item.get("quota_usd")
                    else None,
                    monthly_quota_usd=Decimal(item["monthly_quota_usd"])
                    if item.get("monthly_quota_usd")
                    else None,
                    monthly_reset_policy=item.get("monthly_reset_policy"),
                    monthly_quota_start=datetime.utcnow()
                    if item.get("monthly_quota_usd")
                    else None,
                    allowed_ips=item.get("allowed_ips", []),
                    notify_emails=item.get("notify_emails", []),
                    token_metadata=item.get("token_metadata"),
                    is_active=item.get("is_active", True),
                )
                self.db.add(token)
                await self.db.flush()

                # Create model associations
                for model_name in item.get("allowed_models", []):
                    model = Model(
                        token_id=token.id,
                        model_name=model_name,
                        is_active=True,
                    )
                    self.db.add(model)

                generated_keys.append(
                    {
                        "name": name,
                        "user_email": user_email,
                        "token": plain_token,
                    }
                )
                sr.created += 1

        await self.db.flush()
        return sr, generated_keys

    async def _sync_token_models(self, token_id, model_names: list[str]) -> None:
        """Sync allowed models for a token: deactivate removed, add/reactivate new ones."""
        # Include soft-deleted rows so they can be reactivated instead of duplicated
        result = await self.db.execute(select(Model).where(Model.token_id == token_id))
        existing_models = {m.model_name: m for m in result.scalars().all()}

        desired = set(model_names)
        current = set(existing_models.keys())

        # Deactivate models no longer in the list
        for name in current - desired:
            existing_models[name].is_active = False
            existing_models[name].is_deleted = True
            existing_models[name].deleted_at = datetime.utcnow()

        # Re-activate or create models in the list
        for name in desired:
            if name in existing_models:
                existing_models[name].is_active = True
                existing_models[name].is_deleted = False
                existing_models[name].deleted_at = None
            else:
                self.db.add(Model(token_id=token_id, model_name=name, is_active=True))

    async def _import_team_members(
        self, members_data: list[dict], strategy: str
    ) -> SectionResult:
        sr = SectionResult()
        for item in members_data:
            team_name = item.get("team_name")
            token_name = item.get("token_name")
            token_user_email = item.get("token_user_email")

            if not team_name or not token_name or not token_user_email:
                sr.errors.append(f"TeamMember entry missing required fields: {item}")
                continue

            # Resolve team
            team_result = await self.db.execute(
                select(Team).where(Team.name == team_name, Team.is_active.is_(True))
            )
            team = team_result.scalar_one_or_none()
            if not team:
                sr.errors.append(f"TeamMember: team '{team_name}' not found")
                continue

            # Resolve token
            user = await self._resolve_user_by_email(token_user_email)
            if not user:
                sr.errors.append(f"TeamMember: user '{token_user_email}' not found")
                continue

            token_result = await self.db.execute(
                select(APIToken).where(
                    APIToken.name == token_name,
                    APIToken.user_id == user.id,
                    APIToken.is_deleted.is_(False),
                )
            )
            token = token_result.scalar_one_or_none()
            if not token:
                sr.errors.append(
                    f"TeamMember: token '{token_name}' for '{token_user_email}' not found"
                )
                continue

            # Check existing
            existing_result = await self.db.execute(
                select(TeamMember).where(
                    TeamMember.team_id == team.id, TeamMember.token_id == token.id
                )
            )
            existing = existing_result.scalar_one_or_none()

            if existing:
                if strategy == "skip":
                    sr.skipped += 1
                else:
                    if item.get("allocated_usd"):
                        existing.allocated_usd = Decimal(item["allocated_usd"])
                    sr.overwritten += 1
            else:
                member = TeamMember(
                    team_id=team.id,
                    token_id=token.id,
                    allocated_usd=Decimal(item["allocated_usd"])
                    if item.get("allocated_usd")
                    else None,
                )
                self.db.add(member)
                sr.created += 1

        await self.db.flush()
        return sr

    async def _import_alert_rules(
        self, rules_data: list[dict], strategy: str
    ) -> SectionResult:
        sr = SectionResult()
        for item in rules_data:
            user_email = item.get("user_email")
            rule_key = item.get("rule_key")
            alert_type = item.get("alert_type")

            if not user_email or not rule_key or not alert_type:
                sr.errors.append(f"AlertRule entry missing required fields: {item}")
                continue

            user = await self._resolve_user_by_email(user_email)
            if not user:
                sr.errors.append(f"AlertRule: user '{user_email}' not found")
                continue

            # Resolve optional token
            token_id = None
            if item.get("token_name") and item.get("token_user_email"):
                token_user = await self._resolve_user_by_email(item["token_user_email"])
                if token_user:
                    tok_result = await self.db.execute(
                        select(APIToken.id).where(
                            APIToken.name == item["token_name"],
                            APIToken.user_id == token_user.id,
                            APIToken.is_deleted.is_(False),
                        )
                    )
                    token_id = tok_result.scalar_one_or_none()

            # Resolve optional team
            team_id = None
            if item.get("team_name"):
                team_result = await self.db.execute(
                    select(Team.id).where(
                        Team.name == item["team_name"], Team.is_active.is_(True)
                    )
                )
                team_id = team_result.scalar_one_or_none()

            # A declared scope that fails to resolve must error, not silently
            # degrade the rule to a global (unscoped) rule — which the alert
            # engine forbids (see create_rule in services/alert.py).
            if item.get("token_name") and token_id is None:
                sr.errors.append(
                    f"AlertRule '{rule_key}' for '{user_email}': "
                    f"token '{item['token_name']}' not found"
                )
                continue
            if item.get("team_name") and team_id is None:
                sr.errors.append(
                    f"AlertRule '{rule_key}' for '{user_email}': "
                    f"team '{item['team_name']}' not found"
                )
                continue
            if token_id is None and team_id is None:
                sr.errors.append(
                    f"AlertRule '{rule_key}' for '{user_email}': "
                    f"missing token or team scope"
                )
                continue

            # Check existing
            existing_result = await self.db.execute(
                select(AlertRule).where(
                    AlertRule.user_id == user.id,
                    AlertRule.rule_key == rule_key,
                    AlertRule.alert_type == alert_type,
                )
            )
            existing = existing_result.scalar_one_or_none()

            if existing:
                if strategy == "skip":
                    sr.skipped += 1
                else:
                    if item.get("threshold_value"):
                        existing.threshold_value = Decimal(item["threshold_value"])
                    existing.cooldown_hours = item.get(
                        "cooldown_hours", existing.cooldown_hours
                    )
                    existing.notify_email = item.get(
                        "notify_email", existing.notify_email
                    )
                    existing.notify_in_app = item.get(
                        "notify_in_app", existing.notify_in_app
                    )
                    # Scope is validated above to be exactly one of token/team;
                    # assign directly so a changed scope type clears the other
                    # (CheckConstraint forbids both being set).
                    existing.token_id = token_id
                    existing.team_id = team_id
                    sr.overwritten += 1
            else:
                rule = AlertRule(
                    user_id=user.id,
                    alert_type=alert_type,
                    rule_key=rule_key,
                    threshold_value=Decimal(item["threshold_value"])
                    if item.get("threshold_value")
                    else None,
                    cooldown_hours=item.get("cooldown_hours", 24),
                    notify_email=item.get("notify_email"),
                    notify_in_app=item.get("notify_in_app", True),
                    token_id=token_id,
                    team_id=team_id,
                    is_active=True,
                )
                self.db.add(rule)
                sr.created += 1

        await self.db.flush()
        return sr

    async def _import_entra_group_mappings(
        self, mappings_data: list[dict], strategy: str
    ) -> SectionResult:
        sr = SectionResult()
        for item in mappings_data:
            entra_group_id = item.get("entra_group_id")
            if not entra_group_id:
                sr.errors.append("EntraGroupMapping entry missing entra_group_id")
                continue

            result = await self.db.execute(
                select(EntraGroupMapping).where(
                    EntraGroupMapping.entra_group_id == entra_group_id
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                if strategy == "skip":
                    sr.skipped += 1
                else:
                    existing.group_name = item.get("group_name", existing.group_name)
                    if item.get("role"):
                        existing.role = UserRole(item["role"])
                    existing.permissions = item.get("permissions", existing.permissions)
                    existing.priority = item.get("priority", existing.priority)
                    sr.overwritten += 1
            else:
                mapping = EntraGroupMapping(
                    entra_group_id=entra_group_id,
                    group_name=item.get("group_name", ""),
                    role=UserRole(item["role"]) if item.get("role") else UserRole.ADMIN,
                    permissions=item.get("permissions"),
                    priority=item.get("priority", 0),
                )
                self.db.add(mapping)
                sr.created += 1

        await self.db.flush()
        return sr
