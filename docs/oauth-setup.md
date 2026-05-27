# OAuth Setup Guide

Kolya BR Proxy uses OAuth exclusively for authentication (no local username/password). Two OAuth providers are supported:

- **AWS Cognito** (default/recommended) -- AWS-managed user pool authentication
- **Microsoft Entra ID** (Azure AD) -- personal and enterprise Microsoft accounts

Cognito is the default provider selected during deployment via `deploy-all.sh`. Both providers follow the Authorization Code flow with state-based CSRF protection. OAuth state is persisted in the database and validated on callback.

> **Related docs:**
> - [Security Design](security.md) — CORS, CSRF, token security, RBAC, and detailed login flow analysis
> - [Deployment Guide](deployment.md) — Infrastructure setup including OAuth environment variables

---

## AWS Cognito OAuth (Default)

### Step 1: Create a User Pool

1. In the [AWS Console > Cognito](https://console.aws.amazon.com/cognito/), create a new User Pool (or use an existing one).
2. Note the **User Pool ID** (format: `us-west-2_AbCdEfGhI`).

### Step 2: Create an App Client

1. Under your User Pool, go to **App integration** > **App client** > **Create app client**.
2. Select **Confidential client** (server-side).
3. Set:
   - **App client name**: `Kolya BR Proxy`
   - **Generate client secret**: Yes
   - **Allowed callback URLs**: `http://localhost:3000/auth/cognito/callback`
     - For production, add `https://<your-domain>/auth/cognito/callback`
   - **Allowed sign-out URLs**: `http://localhost:3000`
   - **OAuth 2.0 grant types**: Authorization code grant
   - **OpenID Connect scopes**: `openid`, `profile`, `email`
4. Note the **Client ID** and **Client Secret**.

### Step 3: Configure Hosted UI Domain

1. Under **App integration** > **Domain**, set a Cognito domain prefix or custom domain.
2. The OAuth endpoints derive from the User Pool ID:
   - Authorize: `https://<pool-id-suffix>.auth.<region>.amazoncognito.com/oauth2/authorize`
   - Token: `https://<pool-id-suffix>.auth.<region>.amazoncognito.com/oauth2/token`
   - UserInfo: `https://<pool-id-suffix>.auth.<region>.amazoncognito.com/oauth2/userInfo`

### Step 4: Set Environment Variables

```bash
KBR_COGNITO_USER_POOL_ID=us-west-2_EXAMPLE
KBR_COGNITO_CLIENT_ID=<your-cognito-client-id>
KBR_COGNITO_CLIENT_SECRET=<your-cognito-client-secret>
KBR_COGNITO_REGION=us-west-2
KBR_COGNITO_REDIRECT_URIS=http://localhost:3000/auth/cognito/callback
```

> `KBR_COGNITO_REGION` defaults to `KBR_AWS_REGION` if not set.

### Step 5: Create Users

Self-registration is disabled. All users must be created by an administrator.

If you deployed via `deploy-all.sh`, the first admin user is created automatically at the end of Step 1 (Terraform), and a temporary password is emailed to the specified address.

**Create user via AWS CLI**

> **Important:** The user pool uses email as an alias, so `--username` must **not** be an email address. Use a plain username (e.g. the part before `@`), and pass the email via `--user-attributes`.

```bash
aws cognito-idp admin-create-user \
  --user-pool-id us-west-2_AbCdEfGhI \
  --username jdoe \
  --user-attributes Name=email,Value=jdoe@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL \
  --region us-west-2
```

Cognito sends a temporary password to the user's email. On first login, the user will be prompted to set a permanent password (minimum 8 characters, uppercase, lowercase, numbers, and symbols).

To skip the force-change-password flow, set a permanent password directly:

```bash
aws cognito-idp admin-set-user-password \
  --user-pool-id us-west-2_AbCdEfGhI \
  --username jdoe \
  --password 'PermanentPass123!' \
  --permanent \
  --region us-west-2
```

**Create user via AWS Console**

1. Go to [AWS Console > Cognito > User Pools](https://console.aws.amazon.com/cognito/)
2. Select your user pool
3. Go to **Users** tab > **Create user**
4. Fill in email and temporary password
5. The user logs in and sets a permanent password on first login

### Step 6: Test

1. Start the backend and frontend.
2. Visit the login page and click the Cognito login option (this is the default provider).
3. Complete the Cognito hosted UI login flow.

### API Flow

```
Frontend                     Backend                      Cognito
   |                            |                            |
   |-- GET /admin/auth/         |                            |
   |   cognito/login            |                            |
   |   ?redirect_uri=...  ---->|                            |
   |                            |-- generate state --------->|
   |<-- {authorization_url} ----|                            |
   |                            |                            |
   |-- redirect to Cognito ---------------------------------->|
   |                            |                            |
   |<-- redirect with code, state ----------------------------|
   |                            |                            |
   |-- POST /admin/auth/        |                            |
   |   cognito/callback         |                            |
   |   ?code=...&state=... --->|-- exchange code ----------->|
   |                            |<-- access_token -----------|
   |                            |-- get user info ---------->|
   |                            |<-- user profile -----------|
   |                            |                            |
   |<-- {access_token,          |                            |
   |     refresh_token,         |                            |
   |     user}              ----|                            |
```

---

## Microsoft OAuth

### Step 1: Register Application in Azure AD

1. Go to [Azure Portal > App registrations](https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/RegisteredApps) and click **New registration**.
2. Fill in:
   - **Name**: `Kolya BR Proxy`
   - **Supported account types**: "Accounts in any organizational directory and personal Microsoft accounts" (multi-tenant)
   - **Redirect URI**: Platform `Web`, URI `http://localhost:3000/auth/microsoft/callback`
     - For production, add `https://<your-domain>/auth/microsoft/callback`
3. Click **Register**.
4. On the Overview page, note:
   - **Application (client) ID**
   - **Directory (tenant) ID**

### Step 2: Create Client Secret

1. Go to **Certificates & secrets** > **New client secret**.
2. Set description (e.g. `Kolya BR Proxy Secret`) and expiry (up to 24 months).
3. Click **Add** and immediately copy the **Value** (shown only once).

### Step 3: Configure API Permissions

1. Go to **API permissions** > **Add a permission** > **Microsoft Graph** > **Delegated permissions**.
2. Add: `openid`, `profile`, `email`, `User.Read`, `GroupMember.Read.All`.
3. Click **Add permissions**.
4. Click **Grant admin consent for [your tenant]** — this is **required** for `GroupMember.Read.All` (used by Entra ID group sync).

> **Important:** Without admin consent for `GroupMember.Read.All`, Microsoft will return a 403 error during the OAuth login flow when group sync is enabled.

### Step 4: Set Environment Variables

```bash
KBR_MICROSOFT_CLIENT_ID=<your-microsoft-client-id>
KBR_MICROSOFT_CLIENT_SECRET=<your-microsoft-client-secret>
KBR_MICROSOFT_TENANT_ID=common
KBR_MICROSOFT_REDIRECT_URIS=http://localhost:3000/auth/microsoft/callback
```

**Tenant ID options**:

| Value | Supported Accounts |
|-------|-------------------|
| `common` | All Microsoft accounts (personal + enterprise) |
| `organizations` | Enterprise accounts only |
| `consumers` | Personal Microsoft accounts only |
| `<tenant-id>` | Specific organization only |

### Step 5: Test

1. Start the backend and frontend.
2. Visit the login page and click "Sign in with Microsoft".
3. Complete the Microsoft login flow. The account is created (or linked) automatically.

### API Flow

```
Frontend                     Backend                      Microsoft
   |                            |                            |
   |-- GET /admin/auth/         |                            |
   |   microsoft/login          |                            |
   |   ?redirect_uri=...  ---->|                            |
   |                            |-- generate state --------->|
   |<-- {authorization_url} ----|                            |
   |                            |                            |
   |-- redirect to Microsoft -------------------------------->|
   |                            |                            |
   |<-- redirect with code, state ----------------------------|
   |                            |                            |
   |-- POST /admin/auth/        |                            |
   |   microsoft/callback       |                            |
   |   ?code=...&state=... --->|-- exchange code ----------->|
   |                            |<-- access_token -----------|
   |                            |-- get user info ---------->|
   |                            |<-- user profile -----------|
   |                            |                            |
   |<-- {access_token,          |                            |
   |     refresh_token,         |                            |
   |     user}              ----|                            |
```

---

## Entra ID Group Sync

> **See also:** [Security Design — Entra ID Group-Based Access Control](security.md#entra-id-group-based-access-control) for the detailed login flow diagram, fail-closed design rationale, and bootstrap security analysis.

Entra ID Group Sync maps Azure AD security groups to roles and permissions in the system. When enabled, user access is controlled by group membership rather than manual invitations.

### How It Works

1. User logs in via Microsoft OAuth
2. Backend calls Microsoft Graph API `/me/memberOf` to get the user's security group memberships
3. Groups are matched against the `entra_group_mappings` table (highest priority wins)
4. The matching group determines the user's role and permissions (**overwritten on every login**)
5. If no group matches → 403 denied
6. If Graph API fails (network error, 401, 429, 500) → 503 denied (fail closed)

### Bootstrap (First Login)

When `KBR_MICROSOFT_ENABLE_GROUP_SYNC=true` but no group mappings exist in the database **and** no Microsoft users exist yet, the very first Microsoft login automatically receives `super_admin`. This solves the chicken-and-egg problem.

**The bootstrap window closes immediately** — once the first Microsoft user exists in the DB, subsequent logins are rejected with "Group mappings not configured" until the super_admin creates mappings via the **Entra Groups** page.

> **Important:** Do NOT enable group sync and share the login URL until you're ready to be the first person to log in. The first login claims the bootstrap super_admin slot.

### Configuration

1. **Enable group sync** (environment variable or configmap):
   ```bash
   KBR_MICROSOFT_ENABLE_GROUP_SYNC=true
   ```

2. **Create security groups in Azure Portal**:
   - Go to Azure Portal > Groups > New group
   - Type: Security
   - Add members who should have access

3. **Configure group mappings** in the admin dashboard:
   - Navigate to **Entra Groups** in the sidebar
   - Click **Add Mapping**
   - Fill in:
     - **Entra Group ID**: The Azure group's Object ID (found in Azure Portal > Groups > [group] > Overview)
     - **Group Name**: Display name
     - **Role**: `super_admin` or `admin`
     - **Permissions**: (for admin role) which resources the group can manage
     - **Priority**: Higher number wins when a user belongs to multiple groups

### Behavior Summary

| Scenario | Result |
|----------|--------|
| Group sync disabled (`false`) | All Microsoft users get `admin` role (legacy behavior) |
| Group sync enabled, no mappings, no MS users | First user gets `super_admin` (bootstrap) |
| Group sync enabled, no mappings, MS users exist | Login denied — 403 "Group mappings not configured" |
| Group sync enabled, mappings configured | User must be in a mapped group to login |
| User in multiple mapped groups | Highest `priority` group's role/permissions apply |
| User not in any mapped group | Login denied — 403 "Not authorized" |
| Graph API unreachable / returns error | Login denied — 503 "Unable to verify group membership" |
| User deactivated in KBP | Login denied — 403 regardless of group membership |
| Microsoft user's role edited in UI | Not possible — edit button disabled when group sync active |

### Environment Variable

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KBR_MICROSOFT_ENABLE_GROUP_SYNC` | No | `false` | Enable Entra ID group-to-permission mapping |

---

## All OAuth Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KBR_COGNITO_USER_POOL_ID` | For Cognito | -- | Cognito User Pool ID |
| `KBR_COGNITO_CLIENT_ID` | For Cognito | -- | Cognito app client ID |
| `KBR_COGNITO_CLIENT_SECRET` | For Cognito | -- | Cognito app client secret |
| `KBR_COGNITO_REGION` | No | `KBR_AWS_REGION` | Cognito region |
| `KBR_COGNITO_REDIRECT_URIS` | No | `http://localhost:3000/auth/cognito/callback` | Allowed redirect URIs (comma-separated) |
| `KBR_MICROSOFT_CLIENT_ID` | For MS OAuth | -- | Microsoft app client ID |
| `KBR_MICROSOFT_CLIENT_SECRET` | For MS OAuth | -- | Microsoft app client secret |
| `KBR_MICROSOFT_TENANT_ID` | No | `common` | Azure AD tenant ID |
| `KBR_MICROSOFT_REDIRECT_URIS` | No | `http://localhost:3000/auth/microsoft/callback` | Allowed redirect URIs (comma-separated) |
| `KBR_MICROSOFT_ENABLE_GROUP_SYNC` | No | `false` | Enable Entra ID group-based access control |

---

## Security Recommendations

1. **Rotate client secrets regularly** (every 6-12 months).
2. **Store secrets in environment variables** or a secrets manager -- never commit them to Git.
3. **Use Azure Key Vault / AWS Secrets Manager in production** for secret storage.
4. **Restrict redirect URIs** to only trusted domains.
5. **Use HTTPS in production** for all OAuth redirect URIs.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Redirect URI mismatch | Ensure the URI registered in Azure/Cognito matches exactly (including trailing slashes, protocol, port) |
| Invalid client secret | Secret may be expired -- regenerate in Azure Portal / Cognito console |
| Insufficient permissions | Verify `openid`, `profile`, `email`, `GroupMember.Read.All` scopes are granted with admin consent |
| Microsoft login returns 403 (before callback) | `GroupMember.Read.All` needs admin consent — go to App Registration > API permissions > Grant admin consent |
| Microsoft callback returns 403 "not authorized" | User is not in any mapped Entra group (when group sync is enabled) |
| Microsoft callback returns 403 "Group mappings not configured" | Group sync enabled but no mappings created yet, and bootstrap slot already taken |
| Microsoft callback returns 503 "Unable to verify group membership" | Graph API call to `/me/memberOf` failed — check network, token scopes, admin consent |
| Microsoft user's role reverts after manual edit | Expected — group sync overwrites role on every login; edit the group mapping instead |
| Cognito authorize request canceled | Check that `KBR_COGNITO_DOMAIN` matches the actual Cognito domain (verify with `aws cognito-idp describe-user-pool --query UserPool.Domain`) |
| Cognito callback URL mismatch | Ensure `https://<your-domain>/auth/cognito/callback` is added to the Cognito app client's allowed callback URLs |
| Cognito OAuth not configured (501) | Check that `KBR_COGNITO_USER_POOL_ID`, `KBR_COGNITO_CLIENT_ID`, and `KBR_COGNITO_CLIENT_SECRET` are all set |
| Microsoft OAuth not configured (501) | Check that `KBR_MICROSOFT_CLIENT_ID` and `KBR_MICROSOFT_CLIENT_SECRET` are set |

## Reference Documentation

- [AWS Cognito Developer Guide](https://docs.aws.amazon.com/cognito/latest/developerguide/)
- [Cognito User Pool App Client](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html)
- [Microsoft identity platform](https://learn.microsoft.com/en-us/azure/active-directory/develop/)
- [Azure AD app registration quickstart](https://learn.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)
