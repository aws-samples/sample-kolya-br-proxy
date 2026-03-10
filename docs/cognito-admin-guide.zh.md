# Cognito 用户管理 - 管理员指南

## 概述

本指南说明管理员如何管理 AWS Cognito User Pool 中的用户。

## 前置条件

- 已配置 AWS CLI 和相应凭证
- Cognito User Pool ID: `us-west-2_IrobBcDpA`
- AWS 区域: `us-west-2`

## 用户管理操作

### 1. 创建用户（通过邮件发送临时密码）

创建新用户，Cognito 会自动发送临时密码到用户邮箱：

```bash
aws cognito-idp admin-create-user \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --user-attributes Name=email,Value=user@example.com \
  --region us-west-2
```

**执行后会发生：**
- Cognito 生成临时密码
- 发送邮件给用户，包含登录凭证
- 用户首次登录时必须修改密码
- 临时密码 7 天后过期

### 2. 列出所有用户

```bash
aws cognito-idp list-users \
  --user-pool-id us-west-2_IrobBcDpA \
  --region us-west-2
```

### 3. 重置用户密码

如果用户忘记密码，发送新的临时密码：

```bash
aws cognito-idp admin-reset-user-password \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --region us-west-2
```

### 4. 直接设置永久密码（不发送邮件）

直接设置永久密码，不发送邮件通知：

```bash
aws cognito-idp admin-set-user-password \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --password "NewPassword@123" \
  --permanent \
  --region us-west-2
```

### 5. 删除用户

```bash
aws cognito-idp admin-delete-user \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --region us-west-2
```

### 6. 禁用用户账户

```bash
aws cognito-idp admin-disable-user \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --region us-west-2
```

### 7. 启用用户账户

```bash
aws cognito-idp admin-enable-user \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --region us-west-2
```

### 8. 查看用户详情

```bash
aws cognito-idp admin-get-user \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --region us-west-2
```

## 密码策略

用户创建的密码必须满足以下要求：
- 最少 8 个字符
- 至少一个小写字母
- 至少一个大写字母
- 至少一个数字
- 至少一个特殊字符

有效密码示例：`MyPass@123`

## 邮箱域名白名单

自助注册仅限于 Terraform 中配置的特定邮箱域名：

```hcl
cognito_allowed_email_domains = ["example.com", "yourcompany.com"]
```

更新允许的域名：
1. 编辑 `iac-612674025488-us-west-2/terraform.tfvars`
2. 运行 `terraform apply -target=module.cognito`

## 用户注册流程

### 管理员创建用户（唯一方式）：
1. 管理员运行 `admin-create-user` 命令
2. 用户收到包含临时密码的邮件
3. 用户在 Cognito 托管页面使用临时密码登录
4. 系统强制用户修改密码
5. 用户可以正常使用系统

**注意：** 自助注册已禁用。所有用户必须由管理员创建。

## 故障排查

### 用户未收到邮件
- 检查垃圾邮件文件夹
- 验证邮箱地址是否正确
- 在 AWS Console 检查 Cognito 邮件配置

### 临时密码过期
- 运行 `admin-reset-user-password` 发送新密码

### 用户被锁定
- 检查账户是否被禁用：`admin-get-user`
- 启用账户：`admin-enable-user`

## 安全注意事项

- 临时密码 7 天后过期
- 用户首次登录必须修改密码
- 多次登录失败可能导致账户临时锁定
- 所有管理员操作都会记录在 CloudTrail 中
