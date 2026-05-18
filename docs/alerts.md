# Usage Alerts

Usage alerts monitor API token and team spending, notifying administrators when thresholds are breached.

## Architecture

```
API Request → record_usage() → check_alerts_for_usage() → AlertNotification (in-app)
                                                         → SES email (optional)
```

Alert checks run **inline** after each usage record is committed — not on a cron schedule. This ensures real-time detection with zero delay.

## Alert Types

### Soft Alerts (Absolute Cost)

Trigger when spending reaches an absolute dollar amount. Available for **all tokens** regardless of quota configuration.

| Rule Key | Label | Unit | Window |
|----------|-------|------|--------|
| `monthly_cost` | Monthly cost reached | $ | 1st of month 00:00 → now |
| `daily_cost` | Daily cost reached | $ | Today 00:00 → now |
| `hourly_cost` | Hourly cost reached | $ | Current hour XX:00 → now |
| `lifetime_cost` | Total cost reached | $ | All time |

All time windows are **fixed** (not sliding), reset at the boundary.

### Hard Alerts (Quota Percentage)

Trigger when spending reaches a percentage of the configured quota. Only available for tokens **with quotas**.

| Rule Key | Label | Unit | Prerequisite |
|----------|-------|------|-------------|
| `lifetime_quota_pct` | Total quota usage | % | Token has `quota_usd` |
| `monthly_quota_pct` | Monthly quota usage | % | Token is in a team (has `allocated_usd`) |
| `daily_limit_pct` | Daily limit usage | % | Team key + team has `daily_limit_enabled` |
| `team_budget_pct` | Team budget usage | % | Team-scoped rule (uses `monthly_budget_usd`) |

## Rule Visibility by Token Type

The frontend dynamically shows available rules based on token configuration:

| Token Type | Available Rules |
|-----------|----------------|
| Standalone key, no quota | `monthly_cost`, `daily_cost`, `hourly_cost`, `lifetime_cost` |
| Standalone key with `quota_usd` | `lifetime_quota_pct` only |
| Team key | `monthly_quota_pct` + `lifetime_quota_pct` |
| Team key + daily limit enabled | `monthly_quota_pct` + `lifetime_quota_pct` + `daily_limit_pct` |
| Team-scoped rule (from Teams page) | `team_budget_pct` |

## Notification Channels

Each rule independently configures notification delivery:

- **In-app** (default: enabled) — Creates `AlertNotification` record, visible via bell icon in header
- **Email** (optional) — Sends via AWS SES to comma-separated addresses

## Cooldown

Each rule has a `cooldown_hours` setting (default: 24h). After firing, the same rule won't fire again until the cooldown expires. This prevents notification floods when spending stays above threshold.

## Data Model

### AlertRule

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `user_id` | UUID FK | Owner |
| `token_id` | UUID FK (nullable) | Token scope (CASCADE on delete) |
| `team_id` | UUID FK (nullable) | Team scope (CASCADE on delete) |
| `alert_type` | VARCHAR(20) | `soft` or `hard` |
| `rule_key` | VARCHAR(50) | Rule identifier |
| `threshold_value` | NUMERIC(12,4) | Trigger threshold |
| `cooldown_hours` | INTEGER | Hours between notifications |
| `notify_email` | TEXT | Comma-separated email addresses |
| `notify_in_app` | BOOLEAN | Create in-app notification |
| `is_active` | BOOLEAN | Enable/disable without deleting |

Constraint: `token_id` and `team_id` are mutually exclusive.

### AlertNotification

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `user_id` | UUID FK | Recipient |
| `alert_rule_id` | UUID FK (nullable) | Source rule (SET NULL on delete) |
| `rule_key` | VARCHAR(50) | Denormalized for display |
| `scope_type` | VARCHAR(20) | `token` or `team` |
| `scope_name` | VARCHAR(255) | Token/team name at time of alert |
| `current_value` | NUMERIC(12,4) | Value when triggered |
| `threshold_value` | NUMERIC(12,4) | Configured threshold |
| `message` | TEXT | Human-readable message |
| `is_read` | BOOLEAN | Read status |

## API Endpoints

All endpoints require `manage_api_keys` permission.

```
POST   /admin/alerts/rules                          — Create rule
GET    /admin/alerts/rules?token_id=&team_id=       — List rules
PUT    /admin/alerts/rules/{rule_id}                — Update rule
DELETE /admin/alerts/rules/{rule_id}                — Delete rule
GET    /admin/alerts/notifications?unread_only=&limit= — List notifications
GET    /admin/alerts/notifications/unread-count      — Unread count
POST   /admin/alerts/notifications/{id}/read        — Mark read
POST   /admin/alerts/notifications/read-all         — Mark all read
```

## Frontend Integration

- **Token page**: Alert bell icon per token → dialog with rules for that token
- **Team page**: Alert bell icon per team → dialog with team-scoped rules
- **Header**: Notification bell with unread badge, polling every 15 seconds
- **Notification panel**: Shows unread alerts, click to mark read, "Mark all read" button

## Alert Check Flow

```python
async def check_alerts_for_usage(token_id, user_id, db):
    # 1. Load token-scoped active rules
    # 2. If token belongs to a team, also load team-scoped rules
    # 3. Skip if no rules
    # 4. Batch cooldown check — single query for all rule IDs
    # 5. Single aggregation query: total, monthly, daily, hourly cost
    # 6. For team rules: aggregate team-wide usage
    # 7. Calculate metric for each rule ($ or %)
    # 8. Fire notifications for rules that exceed threshold + pass cooldown
    # 9. Batch insert notifications, send emails via asyncio.to_thread
```

## Configuration

| Variable | Description |
|----------|-------------|
| `KBR_ALERT_SES_SENDER_EMAIL` | SES verified sender (e.g. `noreply@kbp.kolya.fun`) |
| `KBR_ALERT_SES_REGION` | AWS region for SES (defaults to `AWS_REGION`) |

If `ALERT_SES_SENDER_EMAIL` is not configured, email notifications are silently skipped.
