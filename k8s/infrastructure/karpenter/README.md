# Karpenter Node Configurations

This directory contains Karpenter EC2NodeClass and NodePool configurations for the EKS cluster.

## Overview

Karpenter is a flexible, high-performance Kubernetes cluster autoscaler that provisions nodes based on pod requirements. This directory contains the node provisioning configurations.

## Files

- `common-ec2nodeclass.yaml` - Defines EC2 instance configuration (AMI, security groups, subnets, IAM role)
- `common-nodepool.yaml` - Defines node pool requirements and limits
- `apply-karpenter-config.sh` - Script to apply configurations with Terraform values

## EC2NodeClass Configuration

The `common-ec2nodeclass.yaml` defines:

- **AMI Family:** Amazon Linux 2023 (AL2023)
- **IAM Role:** Managed by Terraform (karpenter node role)
- **Block Devices:** 30GB gp3 root volume
- **Subnets & Security Groups:** Automatically discovered via tags
- **Instance Metadata:** IMDSv2 required for security

### Customization

To modify instance configuration, edit `common-ec2nodeclass.yaml`:

```yaml
# Change root volume size
blockDeviceMappings:
  - deviceName: /dev/xvda
    ebs:
      volumeSize: 50Gi  # Change from 30Gi

# Use different AMI family
amiFamily: Bottlerocket  # Options: AL2023, AL2, Bottlerocket, Ubuntu
```

## NodePool Configuration

The `common-nodepool.yaml` defines:

- **Architecture:** ARM64 (Graviton processors)
- **Capacity Type:** On-Demand instances
- **Instance Categories:** t (burstable) and m (general purpose)
- **CPU Range:** 2-4 vCPUs
- **Total Limits:** 1000 CPUs, 1000GB memory
- **Consolidation:** Empty nodes removed after 30s

### Customization

To modify node pool requirements:

```yaml
# Add x86_64 architecture
requirements:
  - key: "kubernetes.io/arch"
    operator: In
    values: ["arm64", "amd64"]

# Use spot instances
  - key: "karpenter.sh/capacity-type"
    operator: In
    values: ["spot", "on-demand"]

# Allow larger instances
  - key: "karpenter.k8s.aws/instance-cpu"
    operator: In
    values: ["2", "4", "8", "16"]

# Increase cluster limits
limits:
  cpu: "2000"
  memory: 2000Gi
```

## Installation

### Automated (Recommended)

```bash
./apply-karpenter-config.sh
```

This script:
1. Reads Terraform outputs (cluster name, IAM role)
2. Substitutes template variables
3. Applies configurations to the cluster

### Manual

```bash
# Get values from Terraform
cd ../../iac-612674025488-us-west-2
CLUSTER_NAME=$(terraform output -raw cluster_name)
NODE_ROLE=$(terraform output -raw karpenter_node_iam_role_name)

# Apply with substitution
cd ../k8s/karpenter
sed -e "s/\${subnetSelectorTermsValue}/${CLUSTER_NAME}/g" \
    -e "s/\${node_iam_role_name}/${NODE_ROLE}/g" \
    common-ec2nodeclass.yaml | kubectl apply -f -

kubectl apply -f common-nodepool.yaml
```

## Verification

```bash
# Check EC2NodeClass
kubectl get ec2nodeclass
kubectl describe ec2nodeclass common-nodeclass

# Check NodePool
kubectl get nodepool
kubectl describe nodepool common-nodepool

# Watch Karpenter provision nodes
kubectl logs -n kube-system deployment/karpenter -c controller -f
```

## Testing Karpenter

Deploy a test workload to trigger node provisioning:

```bash
# Create a test deployment
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: inflate
spec:
  replicas: 0
  selector:
    matchLabels:
      app: inflate
  template:
    metadata:
      labels:
        app: inflate
    spec:
      terminationGracePeriodSeconds: 0
      containers:
      - name: inflate
        image: public.ecr.aws/eks-distro/kubernetes/pause:3.7
        resources:
          requests:
            cpu: 1
            memory: 1.5Gi
EOF

# Scale up to trigger provisioning
kubectl scale deployment inflate --replicas=10

# Watch nodes being created
kubectl get nodes -w

# Scale down to test consolidation
kubectl scale deployment inflate --replicas=0

# Cleanup
kubectl delete deployment inflate
```

## Resource Tagging

Karpenter discovers resources (subnets, security groups) using tags:

```
karpenter.sh/discovery: <cluster-name>
```

These tags are automatically added by Terraform when creating VPC and EKS resources.

## Interruption Handling

Karpenter monitors AWS interruption events (spot termination, scheduled maintenance) via SQS queue. The queue is created by Terraform in the `eks-karpenter` module.

## Node Lifecycle

1. **Provisioning:** Karpenter watches for unschedulable pods and provisions nodes matching requirements
2. **Running:** Nodes run workloads until they become underutilized
3. **Consolidation:** Empty nodes are removed after 30s (configurable)
4. **Interruption:** Spot instances are drained before termination

## Advanced Configurations

### Multiple NodePools

You can create multiple NodePools for different workload types:

```bash
# Copy and modify
cp common-nodepool.yaml gpu-nodepool.yaml
# Edit gpu-nodepool.yaml to add GPU requirements
kubectl apply -f gpu-nodepool.yaml
```

### Node Taints and Labels

Add taints/labels to segregate workloads:

```yaml
spec:
  template:
    spec:
      taints:
        - key: workload
          value: batch
          effect: NoSchedule
      labels:
        workload: batch
```

### Different EC2NodeClasses

Create specialized node classes for different use cases:

```bash
cp common-ec2nodeclass.yaml gpu-ec2nodeclass.yaml
# Edit to use GPU AMIs and instance types
kubectl apply -f gpu-ec2nodeclass.yaml
```

## Troubleshooting

### Nodes Not Provisioning

```bash
# Check Karpenter logs
kubectl logs -n kube-system deployment/karpenter -c controller --tail=100

# Check EC2NodeClass events
kubectl describe ec2nodeclass common-nodeclass

# Check NodePool events
kubectl describe nodepool common-nodepool

# Verify IAM role permissions
aws iam get-role --role-name <karpenter-node-role-name>
```

### Nodes Stuck in Provisioning

- Check AWS service quotas (EC2 instance limits)
- Verify subnet availability
- Check security group rules
- Review Karpenter controller logs

### Unexpected Node Termination

- Check consolidation settings in NodePool
- Review interruption events in Karpenter logs
- Verify SQS queue for interruption notifications

## References

- [Karpenter Documentation](https://karpenter.sh/)
- [Karpenter Best Practices](https://aws.github.io/aws-eks-best-practices/karpenter/)
- [EC2NodeClass API](https://karpenter.sh/docs/concepts/nodeclasses/)
- [NodePool API](https://karpenter.sh/docs/concepts/nodepools/)
