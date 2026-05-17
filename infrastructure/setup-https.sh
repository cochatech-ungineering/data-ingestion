#!/usr/bin/env bash
# ALB + CloudFront HTTPS delante del servicio ECS data-ingestion.
# Uso: AWS_PROFILE=cochatech-dev ./infrastructure/setup-https.sh
# Opcional: HTTPS_DOMAIN=api.tudominio.com (requiere validar ACM por DNS)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REGION="${AWS_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-cochatech-dev}"
CLUSTER_NAME="data-ingestion"
SERVICE_NAME="data-ingestion"
CONTAINER_NAME="data-ingestion"
CONTAINER_PORT=8000
ALB_NAME="data-ingestion-alb"
TG_NAME="data-ingestion-tg"
ALB_SG_NAME="data-ingestion-alb-sg"
ECS_SG_NAME="data-ingestion-ecs-sg"
HTTPS_DOMAIN="${HTTPS_DOMAIN:-}"

export AWS_PROFILE="$PROFILE"
export AWS_DEFAULT_REGION="$REGION"
aws() { command aws "$@"; }

echo "==> HTTPS: ALB + CloudFront"

VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
read -ra ALL_SUBNETS <<< "$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[*].SubnetId' --output text)"
ECS_SUBNETS="${ALL_SUBNETS[0]},${ALL_SUBNETS[1]}"

# --- ALB security group ---
ALB_SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=$ALB_SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)
if [[ -z "$ALB_SG_ID" || "$ALB_SG_ID" == "None" ]]; then
  ALB_SG_ID=$(aws ec2 create-security-group \
    --group-name "$ALB_SG_NAME" \
    --description "ALB HTTP data-ingestion" \
    --vpc-id "$VPC_ID" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id "$ALB_SG_ID" --protocol tcp --port 80 --cidr 0.0.0.0/0
  echo "    ALB SG: $ALB_SG_ID"
fi

ECS_SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=$ECS_SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text)
aws ec2 authorize-security-group-ingress \
  --group-id "$ECS_SG_ID" --protocol tcp --port "$CONTAINER_PORT" \
  --source-group "$ALB_SG_ID" 2>/dev/null || true
aws ec2 revoke-security-group-ingress \
  --group-id "$ECS_SG_ID" --protocol tcp --port "$CONTAINER_PORT" --cidr 0.0.0.0/0 2>/dev/null || true

# --- Target group ---
TG_ARN=$(aws elbv2 describe-target-groups --names "$TG_NAME" \
  --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)
if [[ -z "$TG_ARN" || "$TG_ARN" == "None" ]]; then
  TG_ARN=$(aws elbv2 create-target-group \
    --name "$TG_NAME" \
    --protocol HTTP --port "$CONTAINER_PORT" \
    --vpc-id "$VPC_ID" --target-type ip \
    --health-check-path /health \
    --health-check-interval-seconds 30 \
    --matcher HttpCode=200 \
    --query 'TargetGroups[0].TargetGroupArn' --output text)
fi

# --- ALB ---
ALB_ARN=$(aws elbv2 describe-load-balancers --names "$ALB_NAME" \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || true)
if [[ -z "$ALB_ARN" || "$ALB_ARN" == "None" ]]; then
  ALB_ARN=$(aws elbv2 create-load-balancer \
    --name "$ALB_NAME" --type application --scheme internet-facing \
    --subnets "${ALL_SUBNETS[@]}" \
    --security-groups "$ALB_SG_ID" \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text)
fi
ALB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" \
  --query 'LoadBalancers[0].DNSName' --output text)

LISTENER=$(aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" \
  --query 'Listeners[?Port==`80`].ListenerArn' --output text)
if [[ -z "$LISTENER" || "$LISTENER" == "None" ]]; then
  aws elbv2 create-listener \
    --load-balancer-arn "$ALB_ARN" --protocol HTTP --port 80 \
    --default-actions "Type=forward,TargetGroupArn=$TG_ARN" >/dev/null
fi

# --- ECS + ALB ---
HAS_LB=$(aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
  --query 'length(services[0].loadBalancers)' --output text)

if [[ "$HAS_LB" == "0" ]]; then
  echo "==> Vincular ECS al target group"
  aws ecs update-service \
    --cluster "$CLUSTER_NAME" --service "$SERVICE_NAME" \
    --load-balancers "targetGroupArn=$TG_ARN,containerName=$CONTAINER_NAME,containerPort=$CONTAINER_PORT" \
    --network-configuration "awsvpcConfiguration={subnets=[$ECS_SUBNETS],securityGroups=[$ECS_SG_ID],assignPublicIp=ENABLED}" \
    --force-new-deployment >/dev/null
else
  aws ecs update-service \
    --cluster "$CLUSTER_NAME" --service "$SERVICE_NAME" \
    --network-configuration "awsvpcConfiguration={subnets=[$ECS_SUBNETS],securityGroups=[$ECS_SG_ID],assignPublicIp=ENABLED}" \
    --force-new-deployment >/dev/null
fi

echo "    Esperando targets healthy en ALB..."
for _ in $(seq 1 48); do
  HEALTHY=$(aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
    --query 'length(TargetHealthDescriptions[?TargetHealth.State==`healthy`])' --output text 2>/dev/null || echo 0)
  if [[ "${HEALTHY:-0}" -ge 1 ]]; then break; fi
  sleep 5
done
curl -sf "http://${ALB_DNS}/health" >/dev/null && echo "    ALB OK: http://${ALB_DNS}/health" || echo "    ALB aún propagando..."

# --- CloudFront ---
CF_ID=$(aws cloudfront list-distributions --output json 2>/dev/null | python3 -c "
import json,sys
raw=sys.stdin.read().strip()
data=json.loads(raw) if raw else {}
items=(data.get('DistributionList') or {}).get('Items') or []
for d in items:
    if d.get('Comment')=='data-ingestion-api':
        print(d['Id']); break
")

if [[ -z "${CF_ID:-}" ]]; then
  echo "==> Crear distribución CloudFront (HTTPS)"
  DIST_JSON=$(python3 - "$ALB_DNS" "$HTTPS_DOMAIN" <<'PY'
import json, sys, time
alb_dns, domain = sys.argv[1], sys.argv[2]
import os, subprocess
def aws(*a):
    env={**os.environ,"AWS_PROFILE":os.environ.get("AWS_PROFILE","cochatech-dev"),
         "AWS_DEFAULT_REGION":os.environ.get("AWS_DEFAULT_REGION","us-east-1")}
    r = subprocess.run(["aws"]+list(a), capture_output=True, text=True, check=True, env=env)
    raw=r.stdout.strip()
    return json.loads(raw) if raw else {}

cache = aws("cloudfront","list-cache-policies","--type","managed")
cache_id = next(x["CachePolicy"]["Id"] for x in cache["CachePolicyList"]["Items"]
                if x["CachePolicy"]["CachePolicyConfig"]["Name"]=="Managed-CachingDisabled")
origin_req = aws("cloudfront","list-origin-request-policies","--type","managed")
origin_id = next(x["OriginRequestPolicy"]["Id"] for x in origin_req["OriginRequestPolicyList"]["Items"]
                 if x["OriginRequestPolicy"]["OriginRequestPolicyConfig"]["Name"]=="Managed-AllViewerExceptHostHeader")

viewer_cert = {"CloudFrontDefaultCertificate": True}
aliases = {"Quantity": 0}
if domain:
    # custom domain only if cert already issued
    try:
        certs = aws("acm","list-certificates","--region","us-east-1")
        arn = next((c["CertificateArn"] for c in certs.get("CertificateSummaryList",[])
                    if c["DomainName"]==domain and c.get("Status")=="ISSUED"), None)
        if arn:
            viewer_cert = {"ACMCertificateArn": arn, "SSLSupportMethod": "sni-only",
                           "MinimumProtocolVersion": "TLSv1.2_2021"}
            aliases = {"Quantity": 1, "Items": [domain]}
    except Exception:
        pass

cfg = {
    "CallerReference": f"data-ingestion-{int(time.time())}",
    "Comment": "data-ingestion-api",
    "Enabled": True,
    "Aliases": aliases,
    "Origins": {"Quantity": 1, "Items": [{
        "Id": "alb-origin",
        "DomainName": alb_dns,
        "CustomOriginConfig": {
            "HTTPPort": 80, "HTTPSPort": 443,
            "OriginProtocolPolicy": "http-only",
            "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
        },
    }]},
    "DefaultCacheBehavior": {
        "TargetOriginId": "alb-origin",
        "ViewerProtocolPolicy": "redirect-to-https",
        "AllowedMethods": {
            "Quantity": 7,
            "Items": ["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"],
            "CachedMethods": {"Quantity": 2, "Items": ["GET","HEAD"]},
        },
        "CachePolicyId": cache_id,
        "OriginRequestPolicyId": origin_id,
        "Compress": True,
    },
    "ViewerCertificate": viewer_cert,
    "HttpVersion": "http2and3",
    "PriceClass": "PriceClass_100",
}
print(json.dumps(cfg))
PY
)
  CF_OUT=$(aws cloudfront create-distribution --distribution-config "$DIST_JSON")
  CF_ID=$(echo "$CF_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['Distribution']['Id'])")
  CF_DOMAIN=$(echo "$CF_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['Distribution']['DomainName'])")
else
  CF_DOMAIN=$(aws cloudfront get-distribution --id "$CF_ID" \
    --query 'Distribution.DomainName' --output text)
fi

{
  echo "# Generado por infrastructure/setup-https.sh"
  echo "HTTPS_URL=https://${CF_DOMAIN}"
  echo "CLOUDFRONT_DOMAIN=${CF_DOMAIN}"
  echo "CLOUDFRONT_DISTRIBUTION_ID=${CF_ID}"
  echo "ALB_DNS=${ALB_DNS}"
} > infrastructure/https-endpoints.env

echo ""
echo "==> API con SSL:"
echo "    https://${CF_DOMAIN}/health"
echo "    https://${CF_DOMAIN}/docs"
echo ""
echo "    (CloudFront puede tardar 5-15 min en propagar)"
