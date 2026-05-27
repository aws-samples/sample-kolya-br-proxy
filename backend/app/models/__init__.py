"""Database models package."""

# Import all models to ensure they are registered with SQLAlchemy
from app.models.alert import AlertNotification, AlertRule
from app.models.audit_log import AuditLog
from app.models.entra_group_mapping import EntraGroupMapping
from app.models.oauth_state import OAuthState
from app.models.refresh_token import RefreshToken
from app.models.system_config import SystemConfig
from app.models.token import APIToken
from app.models.usage import UsageRecord
from app.models.user import User
from app.models.model_pricing import ModelPricing
from app.models.model import Model
from app.models.team import Team, TeamMember

__all__ = [
    "AlertNotification",
    "AlertRule",
    "EntraGroupMapping",
    "User",
    "APIToken",
    "UsageRecord",
    "SystemConfig",
    "OAuthState",
    "RefreshToken",
    "AuditLog",
    "ModelPricing",
    "Model",
    "Team",
    "TeamMember",
]
