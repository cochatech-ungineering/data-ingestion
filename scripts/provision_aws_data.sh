#!/usr/bin/env bash
# Crea bucket S3 + RDS PostgreSQL para data-ingestion (sin Docker local).
# Uso: AWS_PROFILE=cochatech-dev ./scripts/provision_aws_data.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REGION="${AWS_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-cochatech-dev}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
DB_ID="${RDS_INSTANCE_ID:-data-ingestion-postgres}"
DB_NAME="${RDS_DB_NAME:-ingestion}"
DB_USER="${RDS_MASTER_USER:-ingestion}"
S3_BUCKET="${S3_BUCKET:-cochatech-data-ingestion-raw-${ACCOUNT_ID}}"
OUTPUT_FILE="${AWS_DATA_ENV_FILE:-infrastructure/aws-data.env}"
SECRETS_FILE="${RDS_PASSWORD_FILE:-infrastructure/rds-master-password.txt}"
RDS_CA="${RDS_CA_FILE:-infrastructure/rds-ca-global.pem}"

export AWS_PROFILE="$PROFILE"
export AWS_DEFAULT_REGION="$REGION"

aws() { command aws "$@"; }

echo "==> Cuenta: $ACCOUNT_ID | Región: $REGION | Perfil: $PROFILE"

mkdir -p "$(dirname "$OUTPUT_FILE")"

if [[ ! -f "$RDS_CA" ]]; then
  echo "==> Descargando certificado RDS CA..."
  curl -fsSL -o "$RDS_CA" https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
fi

echo "==> S3 bucket: $S3_BUCKET"
if aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
  echo "    Bucket ya existe"
else
  if [[ "$REGION" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$S3_BUCKET"
  else
    aws s3api create-bucket --bucket "$S3_BUCKET" \
      --create-bucket-configuration "LocationConstraint=$REGION"
  fi
  aws s3api put-public-access-block --bucket "$S3_BUCKET" \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  echo "    Bucket creado"
fi

if [[ -f "$SECRETS_FILE" ]]; then
  DB_PASSWORD=$(tr -d '\n' < "$SECRETS_FILE")
  echo "==> Usando contraseña existente en $SECRETS_FILE"
else
  DB_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)
  printf '%s' "$DB_PASSWORD" > "$SECRETS_FILE"
  chmod 600 "$SECRETS_FILE"
  echo "==> Contraseña RDS guardada en $SECRETS_FILE (no commitear)"
fi

VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
SG_NAME="data-ingestion-rds-sg"

echo "==> Security group en VPC $VPC_ID"
SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)
if [[ -z "$SG_ID" || "$SG_ID" == "None" ]]; then
  SG_ID=$(aws ec2 create-security-group \
    --group-name "$SG_NAME" \
    --description "RDS PostgreSQL data-ingestion" \
    --vpc-id "$VPC_ID" \
    --query GroupId --output text)
  aws ec2 authorize-security-group-ingress \
    --group-id "$SG_ID" \
    --protocol tcp --port 5432 --cidr 0.0.0.0/0
  echo "    SG creado: $SG_ID (5432 abierto a 0.0.0.0/0 — restringir en producción)"
else
  echo "    SG existente: $SG_ID"
fi

STATUS=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" \
  --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null || echo "none")

if [[ "$STATUS" == "none" || "$STATUS" == "None" ]]; then
  echo "==> Creando RDS $DB_ID (db.t4g.micro, ~5-10 min)..."
  aws rds create-db-instance \
    --db-instance-identifier "$DB_ID" \
    --db-instance-class db.t4g.micro \
    --engine postgres \
    --engine-version 16 \
    --master-username "$DB_USER" \
    --master-user-password "$DB_PASSWORD" \
    --allocated-storage 20 \
    --db-name "$DB_NAME" \
    --vpc-security-group-ids "$SG_ID" \
    --publicly-accessible \
    --backup-retention-period 1 \
    --no-multi-az \
    --storage-encrypted
  echo "    Esperando instancia disponible..."
  aws rds wait db-instance-available --db-instance-identifier "$DB_ID"
else
  echo "==> RDS $DB_ID ya existe (estado: $STATUS)"
  if [[ "$STATUS" != "available" ]]; then
    echo "    Esperando available..."
    aws rds wait db-instance-available --db-instance-identifier "$DB_ID"
  fi
fi

DB_HOST=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" \
  --query 'DBInstances[0].Endpoint.Address' --output text)
DB_PORT=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" \
  --query 'DBInstances[0].Endpoint.Port' --output text)

ENCODED_PASSWORD=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$DB_PASSWORD''', safe=''))")
DATABASE_URL="postgresql://${DB_USER}:${ENCODED_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}?sslmode=require"

echo "==> Aplicando migración SQL..."
export DATABASE_URL
if [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi
"$PYTHON" scripts/migrate_db.py migrations/001_ingestion_jobs.sql

{
  echo "# Generado por scripts/provision_aws_data.sh"
  echo "AWS_REGION=$REGION"
  echo "AWS_PROFILE=$PROFILE"
  echo "S3_BUCKET=$S3_BUCKET"
  echo "DATABASE_URL=$DATABASE_URL"
  echo "DATABASE_SSL_CA=$RDS_CA"
  echo "RDS_INSTANCE_ID=$DB_ID"
  echo "RDS_ENDPOINT=$DB_HOST"
} > "$OUTPUT_FILE"

echo ""
echo "==> Listo. Variables en $OUTPUT_FILE"
echo "    Copia S3_BUCKET y DATABASE_URL a tu .env"
grep -E '^(S3_BUCKET|RDS_ENDPOINT)=' "$OUTPUT_FILE"
