# Kolya BR Proxy -- Kubernetes Manifests

Kubernetes deployment configuration for the Kolya BR Proxy project, split into infrastructure and application layers.

## Directory Structure

```
k8s/
├── deploy.sh                  # Unified deployment script
├── infrastructure/            # Infra team (Helm charts, Karpenter)
│   ├── helm-installations/    # ALB Controller, Karpenter, Metrics Server
│   └── karpenter/             # EC2NodeClass, NodePool
└── application/               # App team (Deployments, Services, Ingress)
    ├── *.yaml.template        # Templates (env-aware resources, safe to commit)
    ├── *-service.yaml         # Static manifests (safe to commit)
    ├── namespace.yaml
    └── (generated *.yaml)     # Generated from templates by deploy.sh/deploy-all.sh
```

## Quick Start

```bash
# Prerequisites: EKS cluster deployed, kubectl configured
aws eks update-kubeconfig --name <cluster-name> --region us-west-2

# First-time setup (interactive wizard)
./deploy.sh init

# Deploy application
./deploy.sh deploy

# Day-to-day operations
./deploy.sh status    # Check status
./deploy.sh logs      # View logs
./deploy.sh update    # Apply config changes
./deploy.sh delete    # Remove deployment
```

## Documentation

- **[Deployment Guide](../docs/deployment.md)** -- full production and non-production deployment instructions
- **[Architecture](../docs/architecture.md)** -- system design including infrastructure components
- **[Terraform (IaC)](../iac-612674025488-us-west-2/README.md)** -- AWS infrastructure provisioning
