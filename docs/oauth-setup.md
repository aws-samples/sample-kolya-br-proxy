# OAuth Setup Guide

Kolya BR Proxy uses OAuth exclusively for authentication (no local username/password). Two OAuth providers are supported:

- **AWS Cognito** (default/recommended) -- AWS-managed user pool authentication
- **Microsoft Entra ID** (Azure AD) -- personal and enterprise Microsoft accounts

Cognito is the default provider selected during deployment via `deploy-all.sh`. Both providers follow the Authorization Code flow with state-based CSRF protection. OAuth state is persisted in the database and validated on callback.

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
KBR_COGNITO_USER_POOL_ID=us-west-2_AbCdEfGhI
KBR_COGNITO_CLIENT_ID=1a2b3c4d5e6f7g8h9i
KBR_COGNITO_CLIENT_SECRET=your-cognito-client-secret
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
2. Add: `openid`, `profile`, `email`, `User.Read`.
3. Click **Add permissions**.
4. For enterprise tenants, click **Grant admin consent** (optional).

### Step 4: Set Environment Variables

```bash
KBR_MICROSOFT_CLIENT_ID=12345678-1234-1234-1234-123456789abc
KBR_MICROSOFT_CLIENT_SECRET=abcdefghijklmnopqrstuvwxyz123456~_
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
| Insufficient permissions | Verify `openid`, `profile`, `email` scopes are granted |
| Cognito authorize request canceled | Check that `KBR_COGNITO_DOMAIN` matches the actual Cognito domain (verify with `aws cognito-idp describe-user-pool --query UserPool.Domain`) |
| Cognito callback URL mismatch | Ensure `https://<your-domain>/auth/cognito/callback` is added to the Cognito app client's allowed callback URLs |
| Cognito OAuth not configured (501) | Check that `KBR_COGNITO_USER_POOL_ID`, `KBR_COGNITO_CLIENT_ID`, and `KBR_COGNITO_CLIENT_SECRET` are all set |
| Microsoft OAuth not configured (501) | Check that `KBR_MICROSOFT_CLIENT_ID` and `KBR_MICROSOFT_CLIENT_SECRET` are set |

## Reference Documentation

- [AWS Cognito Developer Guide](https://docs.aws.amazon.com/cognito/latest/developerguide/)
- [Cognito User Pool App Client](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html)
- [Microsoft identity platform](https://learn.microsoft.com/en-us/azure/active-directory/develop/)
- [Azure AD app registration quickstart](https://learn.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)
