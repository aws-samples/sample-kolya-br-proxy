#!/bin/bash

# Setup security checks for kolya-br-proxy project
# This script only installs dependencies and creates baseline files
# You need to manually run pre-commit checks for security reasons

set -e

echo "🔧 Setting up security checks (no auto-install)..."

# Install dependencies using uv
echo "📦 Installing dependencies..."
uv sync

# Update secrets baseline if needed
echo "🔍 Creating/updating secrets baseline..."
if [ ! -f .secrets.baseline ]; then
    echo "Creating initial secrets baseline..."
    uv run detect-secrets scan --exclude-files '.*\.lock$|.*\.tfstate$|.*\.terraform/.*$|.*\.git/.*$' . > .secrets.baseline
else
    echo "Updating existing secrets baseline..."
    uv run detect-secrets scan --baseline .secrets.baseline --exclude-files '.*\.lock$|.*\.tfstate$|.*\.terraform/.*$|.*\.git/.*$' . --update .secrets.baseline
fi

echo "✅ Security tools setup complete!"
echo ""
echo "🛡️  Available security checks:"
echo "  - AWS credentials detection"
echo "  - Hardcoded secrets detection"
echo "  - Terraform validation and linting"
echo "  - Code formatting checks"
echo ""
echo "💡 Manual usage:"
echo "  - Run 'uv run pre-commit run --all-files' to check all files"
echo "  - Run 'uv run pre-commit run aws-secrets-check' for AWS credential check"
echo "  - Run 'uv run detect-secrets scan --baseline .secrets.baseline' for secrets scan"
echo "  - Run 'uv run detect-secrets audit .secrets.baseline' to review detected secrets"
echo ""
echo "⚠️  Note: Pre-commit hooks are NOT automatically installed for security reasons."
echo "    You can manually install them with 'uv run pre-commit install' if desired."
