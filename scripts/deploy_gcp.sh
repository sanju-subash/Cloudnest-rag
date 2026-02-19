#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID=""
REGION="asia-south1"
SERVICE_NAME="cloudnest-rag"
RUNTIME_SERVICE_ACCOUNT=""
GEMINI_SECRET_NAME="gemini-api-key"

usage() {
  cat <<EOF
Usage:
  ./scripts/deploy_gcp.sh --project-id YOUR_PROJECT_ID [options]

Options:
  --project-id            GCP project id (required)
  --region                Cloud Run region (default: asia-south1)
  --service-name          Cloud Run service name (default: cloudnest-rag)
  --runtime-sa            Runtime service account email (optional)
  --gemini-secret-name    Secret Manager secret name (default: gemini-api-key)
  -h, --help              Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id)
      PROJECT_ID="$2"
      shift 2
      ;;
    --region)
      REGION="$2"
      shift 2
      ;;
    --service-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --runtime-sa)
      RUNTIME_SERVICE_ACCOUNT="$2"
      shift 2
      ;;
    --gemini-secret-name)
      GEMINI_SECRET_NAME="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$PROJECT_ID" ]]; then
  echo "Error: --project-id is required."
  usage
  exit 1
fi

echo "[1/6] Setting project..."
gcloud config set project "$PROJECT_ID" >/dev/null

if [[ -z "$RUNTIME_SERVICE_ACCOUNT" ]]; then
  echo "Runtime service account not provided. Using default Compute Engine service account..."
  PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
  RUNTIME_SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi

echo "[2/6] Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com >/dev/null

echo "[3/6] Checking secret '${GEMINI_SECRET_NAME}'..."
if ! gcloud secrets describe "$GEMINI_SECRET_NAME" >/dev/null 2>&1; then
  echo "Error: Secret '${GEMINI_SECRET_NAME}' not found. Create it first with your Gemini API key."
  exit 1
fi

echo "[4/6] Granting secret access to runtime service account..."
gcloud secrets add-iam-policy-binding "$GEMINI_SECRET_NAME" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor" >/dev/null

echo "[5/6] Building container image..."
gcloud builds submit --tag "gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "[6/6] Deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --image "gcr.io/${PROJECT_ID}/${SERVICE_NAME}" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --service-account "$RUNTIME_SERVICE_ACCOUNT" \
  --set-secrets "GEMINI_API_KEY=${GEMINI_SECRET_NAME}:latest" \
  --set-env-vars "MODEL_NAME=gemini-2.5-flash,RESTAURANT_NAME=CloudNest Restaurant,RESTAURANT_ADDRESS=India,INVOICE_LOGO_PATH=/app/data/invoice_logo.png"

SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format='value(status.url)')"
echo "Deployment complete."
echo "Service URL: ${SERVICE_URL}"
echo "Health check: ${SERVICE_URL}/healthz"
