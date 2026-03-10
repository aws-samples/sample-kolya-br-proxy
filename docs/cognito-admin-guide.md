# Cognito User Management - Admin Guide

## Overview

This guide explains how administrators can manage users in AWS Cognito User Pool.

## Prerequisites

- AWS CLI configured with appropriate credentials
- Cognito User Pool ID: `us-west-2_IrobBcDpA`
- AWS Region: `us-west-2`

## User Management Operations

### 1. Create User (Send Temporary Password via Email)

Create a new user and Cognito will automatically send a temporary password to their email:

```bash
aws cognito-idp admin-create-user \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --user-attributes Name=email,Value=user@example.com \
  --region us-west-2
```

**What happens:**
- Cognito generates a temporary password
- Email is sent to the user with login credentials
- User must change password on first login
- Temporary password expires in 7 days

### 2. List All Users

```bash
aws cognito-idp list-users \
  --user-pool-id us-west-2_IrobBcDpA \
  --region us-west-2
```

### 3. Reset User Password

If a user forgets their password, send them a new temporary password:

```bash
aws cognito-idp admin-reset-user-password \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --region us-west-2
```

### 4. Set Permanent Password (Without Email)

Set a permanent password directly without sending email:

```bash
aws cognito-idp admin-set-user-password \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --password "NewPassword@123" \
  --permanent \
  --region us-west-2
```

### 5. Delete User

```bash
aws cognito-idp admin-delete-user \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --region us-west-2
```

### 6. Disable User Account

```bash
aws cognito-idp admin-disable-user \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --region us-west-2
```

### 7. Enable User Account

```bash
aws cognito-idp admin-enable-user \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --region us-west-2
```

### 8. Get User Details

```bash
aws cognito-idp admin-get-user \
  --user-pool-id us-west-2_IrobBcDpA \
  --username user@example.com \
  --region us-west-2
```

## Password Policy

Users must create passwords that meet these requirements:
- Minimum 8 characters
- At least one lowercase letter
- At least one uppercase letter
- At least one number
- At least one special character

Example valid password: `MyPass@123`  <!-- pragma: allowlist secret -->

## Email Domain Whitelist

Self-registration is restricted to specific email domains configured in Terraform:

```hcl
cognito_allowed_email_domains = ["example.com", "yourcompany.com"]
```

To update allowed domains:
1. Edit `iac-612674025488-us-west-2/terraform.tfvars`
2. Run `terraform apply -target=module.cognito`

## User Registration Flow

### Admin-Created Users (Only Method):
1. Admin runs `admin-create-user` command
2. User receives email with temporary password
3. User logs in with temporary password at the Cognito hosted UI
4. User is forced to change password
5. User can now access the system

**Note:** Self-registration is disabled. All users must be created by administrators.

## Troubleshooting

### User not receiving email
- Check spam/junk folder
- Verify email address is correct
- Check Cognito email configuration in AWS Console

### Temporary password expired
- Run `admin-reset-user-password` to send a new one

### User locked out
- Check if account is disabled: `admin-get-user`
- Enable account: `admin-enable-user`

## Security Notes

- Temporary passwords expire after 7 days
- Users must change password on first login
- Failed login attempts may temporarily lock the account
- All admin operations are logged in CloudTrail
