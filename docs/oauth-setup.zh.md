# OAuth 配置指南

Kolya BR Proxy 仅使用 OAuth 进行认证（不支持本地用户名/密码）。支持两种 OAuth 提供商：

- **AWS Cognito**（默认/推荐）-- AWS 托管的用户池认证
- **Microsoft Entra ID**（Azure AD）-- 个人和企业 Microsoft 账户

Cognito 是通过 `deploy-all.sh` 部署时默认选择的认证提供商。两种提供商均采用基于 state 参数的 CSRF 防护的授权码流程。OAuth state 持久化存储在数据库中，并在回调时验证。

---

## AWS Cognito OAuth（默认）

### 步骤一：创建用户池

1. 在 [AWS 控制台 > Cognito](https://console.aws.amazon.com/cognito/) 中创建新的用户池（或使用已有的）。
2. 记录 **用户池 ID**（格式：`us-west-2_AbCdEfGhI`）。

### 步骤二：创建应用客户端

1. 在用户池下，进入 **应用集成** > **应用客户端** > **创建应用客户端**。
2. 选择 **机密客户端**（服务端）。
3. 设置：
   - **应用客户端名称**：`Kolya BR Proxy`
   - **生成客户端密钥**：是
   - **允许的回调 URL**：`http://localhost:3000/auth/cognito/callback`
     - 生产环境添加 `https://<your-domain>/auth/cognito/callback`
   - **允许的注销 URL**：`http://localhost:3000`
   - **OAuth 2.0 授权类型**：授权码授权
   - **OpenID Connect 范围**：`openid`、`profile`、`email`
4. 记录 **客户端 ID** 和 **客户端密钥**。

### 步骤三：配置托管 UI 域名

1. 在 **应用集成** > **域** 下，设置 Cognito 域名前缀或自定义域名。
2. OAuth 端点由用户池 ID 推导而来：
   - 授权：`https://<pool-id-suffix>.auth.<region>.amazoncognito.com/oauth2/authorize`
   - 令牌：`https://<pool-id-suffix>.auth.<region>.amazoncognito.com/oauth2/token`
   - 用户信息：`https://<pool-id-suffix>.auth.<region>.amazoncognito.com/oauth2/userInfo`

### 步骤四：设置环境变量

```bash
KBR_COGNITO_USER_POOL_ID=us-west-2_EXAMPLE
KBR_COGNITO_CLIENT_ID=<your-cognito-client-id>
KBR_COGNITO_CLIENT_SECRET=<your-cognito-client-secret>
KBR_COGNITO_REGION=us-west-2
KBR_COGNITO_REDIRECT_URIS=http://localhost:3000/auth/cognito/callback
```

> `KBR_COGNITO_REGION` 未设置时默认使用 `KBR_AWS_REGION`。

### 步骤五：创建用户

自助注册已禁用，所有用户必须由管理员创建。

如果通过 `deploy-all.sh` 部署，第一个管理员用户会在步骤一（Terraform）结束时自动创建，临时密码会发送到指定邮箱。

**通过 AWS CLI 创建用户**

> **注意：** 用户池使用邮箱作为别名，因此 `--username` **不能**是邮箱格式。请使用普通用户名（如邮箱 `@` 前面的部分），邮箱通过 `--user-attributes` 传入。

```bash
aws cognito-idp admin-create-user \
  --user-pool-id us-west-2_AbCdEfGhI \
  --username jdoe \
  --user-attributes Name=email,Value=jdoe@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL \
  --region us-west-2
```

Cognito 会将临时密码发送到用户邮箱。首次登录时，用户会被要求设置永久密码（至少 8 个字符，包含大写字母、小写字母、数字和特殊符号）。

如需跳过强制改密流程，可直接设置永久密码：

```bash
aws cognito-idp admin-set-user-password \
  --user-pool-id us-west-2_AbCdEfGhI \
  --username jdoe \
  --password 'PermanentPass123!' \
  --permanent \
  --region us-west-2
```

**通过 AWS 控制台创建用户**

1. 进入 [AWS 控制台 > Cognito > 用户池](https://console.aws.amazon.com/cognito/)
2. 选择你的用户池
3. 进入 **用户** 标签页 > **创建用户**
4. 填写邮箱和临时密码
5. 用户首次登录时会被要求设置永久密码

### 步骤六：测试

1. 启动后端和前端服务。
2. 访问登录页面，点击 Cognito 登录选项（这是默认认证提供商）。
3. 完成 Cognito 托管 UI 登录流程。

### API 流程

```
前端                         后端                          Cognito
   |                            |                            |
   |-- GET /admin/auth/         |                            |
   |   cognito/login            |                            |
   |   ?redirect_uri=...  ---->|                            |
   |                            |-- 生成 state -------------->|
   |<-- {authorization_url} ----|                            |
   |                            |                            |
   |-- 重定向到 Cognito ---------------------------------->  |
   |                            |                            |
   |<-- 携带 code, state 重定向 ------------------------------|
   |                            |                            |
   |-- POST /admin/auth/        |                            |
   |   cognito/callback         |                            |
   |   ?code=...&state=... --->|-- 交换 code --------------->|
   |                            |<-- access_token -----------|
   |                            |-- 获取用户信息 ------------>|
   |                            |<-- 用户资料 ---------------|
   |                            |                            |
   |<-- {access_token,          |                            |
   |     refresh_token,         |                            |
   |     user}              ----|                            |
```

---

## Microsoft OAuth

### 步骤一：在 Azure AD 中注册应用

1. 访问 [Azure 门户 > 应用注册](https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/RegisteredApps)，点击 **新注册**。
2. 填写以下信息：
   - **名称**：`Kolya BR Proxy`
   - **支持的帐户类型**：「任何组织目录中的帐户和个人 Microsoft 帐户」（多租户）
   - **重定向 URI**：平台选 `Web`，URI 为 `http://localhost:3000/auth/microsoft/callback`
     - 生产环境另外添加 `https://<your-domain>/auth/microsoft/callback`
3. 点击 **注册**。
4. 在概览页面记录：
   - **应用程序（客户端）ID**
   - **目录（租户）ID**

### 步骤二：创建客户端密钥

1. 进入 **证书和密码** > **新客户端密码**。
2. 设置说明（如 `Kolya BR Proxy Secret`）和有效期（最长 24 个月）。
3. 点击 **添加**，并立即复制 **值**（仅显示一次）。

### 步骤三：配置 API 权限

1. 进入 **API 权限** > **添加权限** > **Microsoft Graph** > **委托的权限**。
2. 添加：`openid`、`profile`、`email`、`User.Read`、`GroupMember.Read.All`。
3. 点击 **添加权限**。
4. 点击 **授予管理员同意 [你的租户]** — 这是 `GroupMember.Read.All`（Entra ID 组同步所需）的**必需**步骤。

> **重要：** 如果未授予 `GroupMember.Read.All` 管理员同意，在启用组同步时 Microsoft 会在 OAuth 登录流程中返回 403 错误。

### 步骤四：设置环境变量

```bash
KBR_MICROSOFT_CLIENT_ID=<your-microsoft-client-id>
KBR_MICROSOFT_CLIENT_SECRET=<your-microsoft-client-secret>
KBR_MICROSOFT_TENANT_ID=common
KBR_MICROSOFT_REDIRECT_URIS=http://localhost:3000/auth/microsoft/callback
```

**Tenant ID 选项**：

| 值 | 支持的帐户类型 |
|----|---------------|
| `common` | 所有 Microsoft 帐户（个人 + 企业） |
| `organizations` | 仅企业帐户 |
| `consumers` | 仅个人 Microsoft 帐户 |
| `<tenant-id>` | 仅特定组织 |

### 步骤五：测试

1. 启动后端和前端服务。
2. 访问登录页面，点击「使用 Microsoft 帐户登录」。
3. 完成 Microsoft 登录流程，帐户将自动创建（或关联）。

### API 流程

```
前端                         后端                          Microsoft
   |                            |                            |
   |-- GET /admin/auth/         |                            |
   |   microsoft/login          |                            |
   |   ?redirect_uri=...  ---->|                            |
   |                            |-- 生成 state -------------->|
   |<-- {authorization_url} ----|                            |
   |                            |                            |
   |-- 重定向到 Microsoft ---------------------------------->|
   |                            |                            |
   |<-- 携带 code, state 重定向 ------------------------------|
   |                            |                            |
   |-- POST /admin/auth/        |                            |
   |   microsoft/callback       |                            |
   |   ?code=...&state=... --->|-- 交换 code --------------->|
   |                            |<-- access_token -----------|
   |                            |-- 获取用户信息 ------------>|
   |                            |<-- 用户资料 ---------------|
   |                            |                            |
   |<-- {access_token,          |                            |
   |     refresh_token,         |                            |
   |     user}              ----|                            |
```

---

## Entra ID 组同步

Entra ID 组同步将 Azure AD 安全组映射到系统中的角色和权限。启用后，用户访问权限由组成员身份控制，而非手动邀请。

### 工作原理

1. 用户通过 Microsoft OAuth 登录
2. 后端调用 Microsoft Graph API `/me/memberOf` 获取用户的组成员身份
3. 将组与 `entra_group_mappings` 表进行匹配
4. 最高优先级匹配组决定用户的角色和权限
5. 如果没有匹配的组，拒绝登录（403）

### 引导（首次登录）

当 `KBR_MICROSOFT_ENABLE_GROUP_SYNC=true` 但数据库中尚无组映射时，**第一个登录的用户自动成为 super_admin**。这解决了需要已登录管理员才能配置组映射的鸡生蛋问题。

首次登录后，通过管理面板中的 **Entra Groups** 页面配置组映射（仅 super_admin 可见）。

### 配置步骤

1. **启用组同步**（环境变量或 configmap）：
   ```bash
   KBR_MICROSOFT_ENABLE_GROUP_SYNC=true
   ```

2. **在 Azure 门户中创建安全组**：
   - 进入 Azure 门户 > 组 > 新建组
   - 类型：安全
   - 添加应有访问权限的成员

3. **在管理面板中配置组映射**：
   - 在侧边栏点击 **Entra Groups**
   - 点击 **Add Mapping**
   - 填写：
     - **Entra Group ID**：Azure 组的 Object ID（在 Azure 门户 > 组 > [组名] > 概览中查找）
     - **Group Name**：显示名称
     - **Role**：`super_admin` 或 `admin`
     - **Permissions**：（admin 角色）该组可管理的资源
     - **Priority**：用户属于多个组时，数字大的优先

### 行为汇总

| 场景 | 结果 |
|------|------|
| 组同步关闭（`false`） | 所有 Microsoft 用户获得管理员权限（旧行为） |
| 组同步开启，无映射配置 | 第一个用户获得 super_admin；后续用户也获得 super_admin 直到添加映射 |
| 组同步开启，已配置映射 | 用户必须在已映射的组中才能登录 |
| 用户在多个已映射组中 | 最高优先级组的角色/权限生效 |
| 用户不在任何已映射组中 | 拒绝登录（403） |
| 用户已停用 | 无论组成员身份如何均拒绝登录（403） |

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `KBR_MICROSOFT_ENABLE_GROUP_SYNC` | 否 | `false` | 启用 Entra ID 组到权限的映射 |

---

## 所有 OAuth 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `KBR_COGNITO_USER_POOL_ID` | Cognito 时必填 | -- | Cognito 用户池 ID |
| `KBR_COGNITO_CLIENT_ID` | Cognito 时必填 | -- | Cognito 应用客户端 ID |
| `KBR_COGNITO_CLIENT_SECRET` | Cognito 时必填 | -- | Cognito 应用客户端密钥 |
| `KBR_COGNITO_REGION` | 否 | `KBR_AWS_REGION` | Cognito 区域 |
| `KBR_COGNITO_REDIRECT_URIS` | 否 | `http://localhost:3000/auth/cognito/callback` | 允许的重定向 URI（逗号分隔） |
| `KBR_MICROSOFT_CLIENT_ID` | MS OAuth 时必填 | -- | Microsoft 应用客户端 ID |
| `KBR_MICROSOFT_CLIENT_SECRET` | MS OAuth 时必填 | -- | Microsoft 应用客户端密钥 |
| `KBR_MICROSOFT_TENANT_ID` | 否 | `common` | Azure AD 租户 ID |
| `KBR_MICROSOFT_REDIRECT_URIS` | 否 | `http://localhost:3000/auth/microsoft/callback` | 允许的重定向 URI（逗号分隔） |
| `KBR_MICROSOFT_ENABLE_GROUP_SYNC` | 否 | `false` | 启用 Entra ID 基于组的访问控制 |

---

## 安全建议

1. **定期轮换客户端密钥**（每 6-12 个月）。
2. **使用环境变量**或密钥管理器存储敏感信息 -- 不要提交到 Git。
3. **生产环境使用 Azure Key Vault / AWS Secrets Manager** 存储密钥。
4. **限制重定向 URI** 仅允许受信任的域名。
5. **生产环境所有 OAuth 重定向 URI 使用 HTTPS**。

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| 重定向 URI 不匹配 | 确保在 Azure/Cognito 注册的 URI 完全一致（包括尾部斜杠、协议、端口） |
| 客户端密钥无效 | 密钥可能已过期 -- 在 Azure 门户 / Cognito 控制台重新生成 |
| 权限不足 | 确认 `openid`、`profile`、`email`、`GroupMember.Read.All` 范围已授权并已授予管理员同意 |
| Microsoft 登录返回 403（回调前） | `GroupMember.Read.All` 需要管理员同意 — 前往应用注册 > API 权限 > 授予管理员同意 |
| Microsoft 回调返回 403 "not authorized" | 用户不在任何已映射的 Entra 组中（组同步启用时） |
| Cognito authorize 请求被取消 | 检查 `KBR_COGNITO_DOMAIN` 是否与实际 Cognito 域名一致（通过 `aws cognito-idp describe-user-pool --query UserPool.Domain` 验证） |
| Cognito 回调 URL 不匹配 | 确保 `https://<your-domain>/auth/cognito/callback` 已添加到 Cognito 应用客户端的允许回调 URL 中 |
| Cognito OAuth 未配置（501） | 检查 `KBR_COGNITO_USER_POOL_ID`、`KBR_COGNITO_CLIENT_ID` 和 `KBR_COGNITO_CLIENT_SECRET` 是否均已设置 |
| Microsoft OAuth 未配置（501） | 检查 `KBR_MICROSOFT_CLIENT_ID` 和 `KBR_MICROSOFT_CLIENT_SECRET` 是否已设置 |

## 参考文档

- [AWS Cognito 开发者指南](https://docs.aws.amazon.com/zh_cn/cognito/latest/developerguide/)
- [Cognito 用户池应用客户端](https://docs.aws.amazon.com/zh_cn/cognito/latest/developerguide/user-pool-settings-client-apps.html)
- [Microsoft 标识平台文档](https://learn.microsoft.com/zh-cn/azure/active-directory/develop/)
- [Azure AD 应用注册快速入门](https://learn.microsoft.com/zh-cn/azure/active-directory/develop/quickstart-register-app)
