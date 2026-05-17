#!/usr/bin/env bash
set -euo pipefail

# Despliega data-ingestion en ECS Fargate (ECR + RDS + S3 + SNS).
# Uso: AWS_PROFILE=cochatech-dev ./infrastructure/deploy.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ACCOUNT_ID="545349726305"
REGION="${AWS_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-cochatech-dev}"
REPO_NAME="data-ingestion"
CLUSTER_NAME="data-ingestion"
SERVICE_NAME="data-ingestion"
S3_BUCKET="cochatech-data-ingestion-raw-${ACCOUNT_ID}"
RDS_SG_ID="${RDS_SECURITY_GROUP_ID:-sg-055ee671916a28e68}"
ECS_SG_NAME="data-ingestion-ecs-sg"
IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}:latest"
SECRET_DB_ARN="arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:data-ingestion/database-url-9UUn4x"

export AWS_PROFILE="$PROFILE"
export AWS_DEFAULT_REGION="$REGION"
aws() { command aws "$@"; }

echo "==> Perfil: $PROFILE | Región: $REGION"

# --- Secret DATABASE_URL ---
if [[ ! -f infrastructure/rds-master-password.txt ]]; then
  echo "Falta infrastructure/rds-master-password.txt"
  exit 1
fi
DB_PASS=$(tr -d '\n' < infrastructure/rds-master-password.txt)
DB_HOST=$(aws rds describe-db-instances --db-instance-identifier data-ingestion-postgres \
  --query 'DBInstances[0].Endpoint.Address' --output text)
ENCODED_PASS=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$DB_PASS''', safe=''))")
DATABASE_URL="postgresql://ingestion:${ENCODED_PASS}@${DB_HOST}:5432/ingestion?sslmode=require"

echo "==> Actualizando secret data-ingestion/database-url"
aws secretsmanager put-secret-value \
  --secret-id "$SECRET_DB_ARN" \
  --secret-string "$DATABASE_URL" >/dev/null

# --- IAM task role (S3 + SNS vía rol, sin access keys) ---
echo "==> IAM task role"
aws iam put-role-policy \
  --role-name "data-ingestion-task-role" \
  --policy-name "DataIngestionPermissions" \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [
      {
        \"Effect\": \"Allow\",
        \"Action\": [\"sns:Publish\"],
        \"Resource\": \"arn:aws:sns:${REGION}:${ACCOUNT_ID}:cashback-ingestion\"
      },
      {
        \"Effect\": \"Allow\",
        \"Action\": [
          \"s3:PutObject\", \"s3:GetObject\", \"s3:DeleteObject\",
          \"s3:ListBucket\", \"s3:HeadBucket\", \"s3:CreateBucket\"
        ],
        \"Resource\": [
          \"arn:aws:s3:::${S3_BUCKET}\",
          \"arn:aws:s3:::${S3_BUCKET}/*\"
        ]
      }
    ]
  }" >/dev/null

# --- ECR build & push ---
echo "==> ECR login y push imagen"
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
docker build -t "${REPO_NAME}:latest" .
docker tag "${REPO_NAME}:latest" "$IMAGE_URI"
docker push "$IMAGE_URI"

aws logs create-log-group --log-group-name "/ecs/data-ingestion" --region "$REGION" 2>/dev/null || true

# --- Security group ECS ---
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
ECS_SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=$ECS_SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)
if [[ -z "$ECS_SG_ID" || "$ECS_SG_ID" == "None" ]]; then
  ECS_SG_ID=$(aws ec2 create-security-group \
    --group-name "$ECS_SG_NAME" \
    --description "ECS Fargate data-ingestion API" \
    --vpc-id "$VPC_ID" \
    --query GroupId --output text)
  aws ec2 authorize-security-group-ingress \
    --group-id "$ECS_SG_ID" --protocol tcp --port 8000 --cidr 0.0.0.0/0
  echo "    SG ECS creado: $ECS_SG_ID"
else
  echo "    SG ECS existente: $ECS_SG_ID"
fi

# RDS: permitir Postgres desde tasks ECS
echo "==> Regla RDS (5432 desde $ECS_SG_ID)"
aws ec2 authorize-security-group-ingress \
  --group-id "$RDS_SG_ID" \
  --protocol tcp --port 5432 \
  --source-group "$ECS_SG_ID" 2>/dev/null || echo "    Regla RDS ya existe o no aplicable"

SUBNETS=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[*].SubnetId' --output text | tr '\t' ',')
# Usar hasta 2 subnets en AZ distintas
SUBNET_LIST=$(echo "$SUBNETS" | tr ',' '\n' | head -2 | paste -sd,)

echo "==> Registrar task definition"
aws ecs register-task-definition \
  --cli-input-json file://infrastructure/ecs-task-definition.json \
  --region "$REGION" >/dev/null

aws ecs create-cluster --cluster-name "$CLUSTER_NAME" --region "$REGION" 2>/dev/null || true

SERVICE_EXISTS=$(aws ecs describe-services \
  --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
  --query 'services[?status==`ACTIVE`].serviceName' --output text 2>/dev/null || true)

if [[ -z "$SERVICE_EXISTS" ]]; then
  echo "==> Crear servicio ECS"
  aws ecs create-service \
    --cluster "$CLUSTER_NAME" \
    --service-name "$SERVICE_NAME" \
    --task-definition data-ingestion \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_LIST],securityGroups=[$ECS_SG_ID],assignPublicIp=ENABLED}" \
    --region "$REGION" >/dev/null
else
  echo "==> Actualizar servicio ECS"
  aws ecs update-service \
    --cluster "$CLUSTER_NAME" \
    --service "$SERVICE_NAME" \
    --task-definition data-ingestion \
    --force-new-deployment \
    --region "$REGION" >/dev/null
fi

echo "==> Esperando task en RUNNING (puede tardar 2-3 min)..."
for _ in $(seq 1 36); do
  TASK_ARN=$(aws ecs list-tasks --cluster "$CLUSTER_NAME" --service-name "$SERVICE_NAME" \
    --desired-status RUNNING --query 'taskArns[0]' --output text 2>/dev/null || true)
  if [[ -n "$TASK_ARN" && "$TASK_ARN" != "None" ]]; then
    ENI=$(aws ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$TASK_ARN" --output json | \
      python3 -c "
import json,sys
t=json.load(sys.stdin)['tasks'][0]
for a in t.get('attachments',[]):
    if a.get('type')=='ElasticNetworkInterface':
        for d in a.get('details',[]):
            if d.get('name')=='networkInterfaceId':
                print(d['value']); raise SystemExit
")
    if [[ -n "$ENI" ]]; then
      PUBLIC_IP=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI" \
        --query 'NetworkInterfaces[0].Association.PublicIp' --output text 2>/dev/null || true)
      if [[ -n "$PUBLIC_IP" && "$PUBLIC_IP" != "None" ]]; then
        echo ""
        echo "==> API disponible en: http://${PUBLIC_IP}:8000"
        echo "    Health: http://${PUBLIC_IP}:8000/health"
        echo "    Docs:   http://${PUBLIC_IP}:8000/docs"
        exit 0
      fi
    fi
  fi
  sleep 5
done

echo "Servicio desplegado. Obtén la IP con infrastructure/deploy.sh o describe-tasks."
