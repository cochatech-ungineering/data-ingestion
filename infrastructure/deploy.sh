#!/bin/bash
set -euo pipefail

# Deploy data-ingestion to ECS Fargate
# Run from project root with access to account 545349726305

ACCOUNT_ID="545349726305"
REGION="us-east-1"
REPO_NAME="data-ingestion"
CLUSTER_NAME="data-ingestion"
SERVICE_NAME="data-ingestion"
IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}:latest"

echo "=== Step 1: Create ECR Repository ==="
aws ecr create-repository \
  --repository-name "${REPO_NAME}" \
  --region "${REGION}" \
  --image-scanning-configuration scanOnPush=true \
  2>/dev/null || echo "Repository already exists"

echo "=== Step 2: Login to ECR ==="
aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "=== Step 3: Build and Push Image ==="
docker build -t "${REPO_NAME}:latest" .
docker tag "${REPO_NAME}:latest" "${IMAGE_URI}"
docker push "${IMAGE_URI}"

echo "=== Step 4: Create CloudWatch Log Group ==="
aws logs create-log-group \
  --log-group-name "/ecs/data-ingestion" \
  --region "${REGION}" \
  2>/dev/null || echo "Log group already exists"

echo "=== Step 5: Create IAM Execution Role ==="
aws iam create-role \
  --role-name "ecsTaskExecutionRole" \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' 2>/dev/null || echo "Execution role already exists"

aws iam attach-role-policy \
  --role-name "ecsTaskExecutionRole" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" \
  2>/dev/null || true

# Allow execution role to read secrets
aws iam put-role-policy \
  --role-name "ecsTaskExecutionRole" \
  --policy-name "SecretsManagerRead" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:us-east-1:545349726305:secret:data-ingestion/*"
    }]
  }'

echo "=== Step 6: Create IAM Task Role ==="
aws iam create-role \
  --role-name "data-ingestion-task-role" \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' 2>/dev/null || echo "Task role already exists"

aws iam put-role-policy \
  --role-name "data-ingestion-task-role" \
  --policy-name "DataIngestionPermissions" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": ["sns:Publish"],
        "Resource": "arn:aws:sns:us-east-1:545349726305:cashback-ingestion"
      },
      {
        "Effect": "Allow",
        "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
        "Resource": [
          "arn:aws:s3:::ingestion-raw",
          "arn:aws:s3:::ingestion-raw/*"
        ]
      }
    ]
  }'

echo "=== Step 7: Create Secrets (update values as needed) ==="
aws secretsmanager create-secret \
  --name "data-ingestion/database-url" \
  --secret-string "postgresql://ingestion:CHANGE_ME@your-aurora-endpoint:5432/ingestion" \
  --region "${REGION}" \
  2>/dev/null || echo "Secret already exists — update with: aws secretsmanager put-secret-value ..."

aws secretsmanager create-secret \
  --name "data-ingestion/s3-access-key" \
  --secret-string "CHANGE_ME" \
  --region "${REGION}" \
  2>/dev/null || echo "Secret already exists"

aws secretsmanager create-secret \
  --name "data-ingestion/s3-secret-key" \
  --secret-string "CHANGE_ME" \
  --region "${REGION}" \
  2>/dev/null || echo "Secret already exists"

echo "=== Step 8: Register Task Definition ==="
aws ecs register-task-definition \
  --cli-input-json file://infrastructure/ecs-task-definition.json \
  --region "${REGION}"

echo "=== Step 9: Create ECS Cluster ==="
aws ecs create-cluster \
  --cluster-name "${CLUSTER_NAME}" \
  --region "${REGION}" \
  2>/dev/null || echo "Cluster already exists"

echo "=== Step 10: Create ECS Service ==="
echo ""
echo "⚠️  Before creating the service, you need:"
echo "  1. A VPC with subnets (use default VPC or create one)"
echo "  2. A security group allowing inbound on port 8000"
echo ""
echo "Run this after setting SUBNET_IDS and SG_ID:"
echo ""
echo "  aws ecs create-service \\"
echo "    --cluster ${CLUSTER_NAME} \\"
echo "    --service-name ${SERVICE_NAME} \\"
echo "    --task-definition data-ingestion \\"
echo "    --desired-count 1 \\"
echo "    --launch-type FARGATE \\"
echo "    --network-configuration 'awsvpcConfiguration={subnets=[SUBNET_ID_1,SUBNET_ID_2],securityGroups=[SG_ID],assignPublicIp=ENABLED}' \\"
echo "    --region ${REGION}"
echo ""
echo "=== Done! ==="
echo "Image pushed to: ${IMAGE_URI}"
