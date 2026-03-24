#!/bin/bash
# Deploy the VM CPU auto-scaler to GCP
#
# Prerequisites:
#   1. gcloud CLI authenticated with project ai-calling-9238e
#   2. Cloud Functions API enabled
#   3. Cloud Scheduler API enabled
#   4. Cloud Monitoring API enabled
#
# This creates:
#   - A Cloud Function that checks CPU and resizes the VM
#   - A Cloud Scheduler job that triggers it every 5 minutes

set -euo pipefail

PROJECT="ai-calling-9238e"
REGION="asia-south1"
FUNCTION_NAME="wavelength-vm-autoscaler"
SCHEDULER_JOB="wavelength-autoscale-trigger"

echo "=== Step 1: Enable required APIs ==="
gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudscheduler.googleapis.com \
  monitoring.googleapis.com \
  compute.googleapis.com \
  --project="$PROJECT"

echo "=== Step 2: Deploy Cloud Function ==="
gcloud functions deploy "$FUNCTION_NAME" \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source=. \
  --entry-point=autoscale_vm \
  --trigger-http \
  --allow-unauthenticated \
  --memory=256Mi \
  --timeout=300s \
  --set-env-vars="GCP_PROJECT=$PROJECT,GCP_ZONE=asia-south1-c,GCP_INSTANCE=wavelength-v3,MIN_CPUS=1,MAX_CPUS=4,SCALE_UP_THRESHOLD=70,SCALE_DOWN_THRESHOLD=20" \
  --project="$PROJECT"

# Get the function URL
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
  --gen2 \
  --region="$REGION" \
  --project="$PROJECT" \
  --format="value(serviceConfig.uri)")

echo "Function URL: $FUNCTION_URL"

echo "=== Step 3: Create Cloud Scheduler job (every 5 minutes) ==="
# Delete existing job if present
gcloud scheduler jobs delete "$SCHEDULER_JOB" \
  --location="$REGION" \
  --project="$PROJECT" \
  --quiet 2>/dev/null || true

gcloud scheduler jobs create http "$SCHEDULER_JOB" \
  --location="$REGION" \
  --schedule="*/5 * * * *" \
  --uri="$FUNCTION_URL" \
  --http-method=POST \
  --project="$PROJECT"

echo ""
echo "=== Auto-scaler deployed! ==="
echo "  Function: $FUNCTION_NAME"
echo "  Schedule: Every 5 minutes"
echo "  VM: wavelength-v3 (asia-south1-c)"
echo "  CPU range: 1-4 CPUs"
echo "  Scale up: >70% CPU"
echo "  Scale down: <20% CPU"
echo ""
echo "Test manually:"
echo "  curl -X POST $FUNCTION_URL"
