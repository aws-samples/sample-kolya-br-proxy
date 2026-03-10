#!/bin/bash

# ECR Push Script for Kolya BR Proxy
# This script builds Docker images and pushes them to AWS ECR

set -e

# Configuration
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-612674025488}"
AWS_REGION="${AWS_REGION:-us-west-2}"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
BACKEND_REPO="kolya-br-proxy-backend"
FRONTEND_REPO="kolya-br-proxy-frontend"
IMAGE_TAG="${IMAGE_TAG:-latest}"
PLATFORM="linux/arm64"

echo "=========================================="
echo "Kolya BR Proxy - ECR Push Script"
echo "=========================================="
echo "AWS Account: $AWS_ACCOUNT_ID"
echo "AWS Region: $AWS_REGION"
echo "ECR Registry: $ECR_REGISTRY"
echo "Image Tag: $IMAGE_TAG"
echo "Platform: $PLATFORM"
echo "=========================================="

# Login to ECR
echo "Logging in to ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY

# Create ECR repositories if they don't exist
echo "Ensuring ECR repositories exist..."
aws ecr describe-repositories --repository-names $BACKEND_REPO --region $AWS_REGION 2>/dev/null || \
  aws ecr create-repository --repository-name $BACKEND_REPO --region $AWS_REGION

aws ecr describe-repositories --repository-names $FRONTEND_REPO --region $AWS_REGION 2>/dev/null || \
  aws ecr create-repository --repository-name $FRONTEND_REPO --region $AWS_REGION

# Build and push backend
echo ""
echo "Building backend image..."
docker build \
  --platform $PLATFORM \
  -t $ECR_REGISTRY/$BACKEND_REPO:$IMAGE_TAG \
  -t $ECR_REGISTRY/$BACKEND_REPO:latest \
  -f backend/Dockerfile \
  .

echo "Pushing backend image to ECR..."
docker push $ECR_REGISTRY/$BACKEND_REPO:$IMAGE_TAG
docker push $ECR_REGISTRY/$BACKEND_REPO:latest

# Build and push frontend
echo ""
echo "Building frontend image..."
docker build \
  --platform $PLATFORM \
  -t $ECR_REGISTRY/$FRONTEND_REPO:$IMAGE_TAG \
  -t $ECR_REGISTRY/$FRONTEND_REPO:latest \
  -f frontend/Dockerfile \
  frontend/

echo "Pushing frontend image to ECR..."
docker push $ECR_REGISTRY/$FRONTEND_REPO:$IMAGE_TAG
docker push $ECR_REGISTRY/$FRONTEND_REPO:latest

echo ""
echo "=========================================="
echo "Push completed successfully!"
echo "=========================================="
echo "Backend image: $ECR_REGISTRY/$BACKEND_REPO:$IMAGE_TAG"
echo "Frontend image: $ECR_REGISTRY/$FRONTEND_REPO:$IMAGE_TAG"
echo "=========================================="
