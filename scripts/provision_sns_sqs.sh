#!/usr/bin/env bash
# Provisiona SNS topic + colas SQS en AWS (motor QR, motor transfers).
# Uso: AWS_PROFILE=cochatech-dev ./scripts/provision_sns_sqs.sh

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
TOPIC_NAME="${SNS_TOPIC_NAME:-cashback-ingestion}"
QR_QUEUE="${SQS_QR_QUEUE:-cashback-qr-processor}"
TRANSFERS_QUEUE="${SQS_TRANSFERS_QUEUE:-cashback-transfers-processor}"
QR_DLQ="${QR_QUEUE}-dlq"
TRANSFERS_DLQ="${TRANSFERS_QUEUE}-dlq"
OUTPUT_FILE="${SNS_SQS_ENV_FILE:-infrastructure/sns-sqs.env}"

AWS_OPTS=(--region "$REGION")
if [[ -n "${AWS_ENDPOINT_URL:-}" ]]; then
  AWS_OPTS+=(--endpoint-url "$AWS_ENDPOINT_URL")
fi

aws() { command aws "${AWS_OPTS[@]}" "$@"; }

echo "==> Región: $REGION"
[[ -n "${AWS_ENDPOINT_URL:-}" ]] && echo "==> Endpoint: $AWS_ENDPOINT_URL"

mkdir -p "$(dirname "$OUTPUT_FILE")"

create_queue() {
  local name="$1"
  local dlq_arn="${2:-}"
  if [[ -n "$dlq_arn" ]]; then
    aws sqs create-queue \
      --queue-name "$name" \
      --attributes "{\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"${dlq_arn}\\\",\\\"maxReceiveCount\\\":\\\"5\\\"}\",\"VisibilityTimeout\":\"120\"}" \
      --output text --query 'QueueUrl'
  else
    aws sqs create-queue --queue-name "$name" --output text --query 'QueueUrl'
  fi
}

get_queue_arn() {
  local url="$1"
  aws sqs get-queue-attributes --queue-url "$url" --attribute-names QueueArn \
    --query 'Attributes.QueueArn' --output text
}

set_queue_policy() {
  local queue_url="$1"
  local queue_arn="$2"
  local policy_json attrs
  attrs=$(mktemp)
  policy_json=$(jq -c -n \
    --arg arn "$queue_arn" \
    --arg topic "$TOPIC_ARN" \
    '{
      Version: "2012-10-17",
      Statement: [{
        Sid: "AllowSNSToSend",
        Effect: "Allow",
        Principal: {Service: "sns.amazonaws.com"},
        Action: "sqs:SendMessage",
        Resource: $arn,
        Condition: {ArnEquals: {"aws:SourceArn": $topic}}
      }]
    }')
  jq -n --arg policy "$policy_json" '{Policy: $policy}' > "$attrs"
  aws sqs set-queue-attributes --queue-url "$queue_url" --attributes "file://${attrs}"
  rm -f "$attrs"
}

echo "==> Creando DLQs..."
QR_DLQ_URL=$(create_queue "$QR_DLQ")
TRANSFERS_DLQ_URL=$(create_queue "$TRANSFERS_DLQ")
QR_DLQ_ARN=$(get_queue_arn "$QR_DLQ_URL")
TRANSFERS_DLQ_ARN=$(get_queue_arn "$TRANSFERS_DLQ_URL")

echo "==> Creando colas principales..."
QR_QUEUE_URL=$(create_queue "$QR_QUEUE" "$QR_DLQ_ARN")
TRANSFERS_QUEUE_URL=$(create_queue "$TRANSFERS_QUEUE" "$TRANSFERS_DLQ_ARN")
QR_QUEUE_ARN=$(get_queue_arn "$QR_QUEUE_URL")
TRANSFERS_QUEUE_ARN=$(get_queue_arn "$TRANSFERS_QUEUE_URL")

echo "==> Creando topic SNS: $TOPIC_NAME"
TOPIC_ARN=$(aws sns create-topic --name "$TOPIC_NAME" --query 'TopicArn' --output text)

echo "==> Políticas de cola (SNS → SQS)..."
set_queue_policy "$QR_QUEUE_URL" "$QR_QUEUE_ARN"
set_queue_policy "$TRANSFERS_QUEUE_URL" "$TRANSFERS_QUEUE_ARN"

subscribe_with_filter() {
  local queue_arn="$1"
  local filter_prefix="$2"
  local sub_arn filter
  sub_arn=$(aws sns subscribe \
    --topic-arn "$TOPIC_ARN" \
    --protocol sqs \
    --notification-endpoint "$queue_arn" \
    --return-subscription-arn \
    --query 'SubscriptionArn' --output text)
  filter=$(jq -n --arg p "$filter_prefix" '{event_type: [{prefix: $p}]}')
  aws sns set-subscription-attributes \
    --subscription-arn "$sub_arn" \
    --attribute-name FilterPolicy \
    --attribute-value "$filter"
  echo "    $sub_arn ← prefix '$filter_prefix'"
}

echo "==> Suscripciones con filter policy..."
subscribe_with_filter "$QR_QUEUE_ARN" "qr."
subscribe_with_filter "$TRANSFERS_QUEUE_ARN" "transfers."

{
  echo "# Generado por scripts/provision_sns_sqs.sh — copiar a .env"
  echo "AWS_REGION=$REGION"
  echo "SNS_TOPIC_ARN=$TOPIC_ARN"
  echo "SNS_TOPIC_NAME=$TOPIC_NAME"
  echo "SQS_QR_QUEUE_URL=$QR_QUEUE_URL"
  echo "SQS_QR_QUEUE_ARN=$QR_QUEUE_ARN"
  echo "SQS_TRANSFERS_QUEUE_URL=$TRANSFERS_QUEUE_URL"
  echo "SQS_TRANSFERS_QUEUE_ARN=$TRANSFERS_QUEUE_ARN"
  [[ -n "${AWS_ENDPOINT_URL:-}" ]] && echo "AWS_ENDPOINT_URL=$AWS_ENDPOINT_URL"
} > "$OUTPUT_FILE"

echo ""
echo "==> Listo. Variables en $OUTPUT_FILE"
cat "$OUTPUT_FILE"
