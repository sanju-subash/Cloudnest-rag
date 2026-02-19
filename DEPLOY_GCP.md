# CloudNest RAG on Google Cloud (Cloud Run)

## 1) Prerequisites
- Google Cloud project with billing enabled
- `gcloud` CLI authenticated (`gcloud auth login`)
- APIs enabled:
  - Cloud Run API
  - Cloud Build API
  - Artifact Registry API
  - Secret Manager API

## 2) Create secret for Gemini key (one-time)
```bash
gcloud config set project YOUR_PROJECT_ID
printf "YOUR_GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=-
# If secret already exists, update it:
printf "YOUR_GEMINI_API_KEY" | gcloud secrets versions add gemini-api-key --data-file=-
```

## 3) One-command deployment (PowerShell - Windows)
```powershell
./scripts/deploy_gcp.ps1 -ProjectId YOUR_PROJECT_ID -Region asia-south1 -ServiceName cloudnest-rag
```

Optional args:
- `-RuntimeServiceAccount "your-sa@your-project.iam.gserviceaccount.com"`
- `-GeminiSecretName "gemini-api-key"`

## 4) One-command deployment (Bash - Linux/macOS)
```bash
chmod +x ./scripts/deploy_gcp.sh
./scripts/deploy_gcp.sh --project-id YOUR_PROJECT_ID --region asia-south1 --service-name cloudnest-rag
```

Optional args:
- `--runtime-sa your-sa@your-project.iam.gserviceaccount.com`
- `--gemini-secret-name gemini-api-key`

## 5) Manual deploy (Secret Manager)
```bash
gcloud config set project YOUR_PROJECT_ID

gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/cloudnest-rag

RUNTIME_SA="YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com"

gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor"

gcloud run deploy cloudnest-rag \
  --image gcr.io/YOUR_PROJECT_ID/cloudnest-rag \
  --region asia-south1 \
  --platform managed \
  --allow-unauthenticated \
  --service-account "${RUNTIME_SA}" \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
  --set-env-vars MODEL_NAME=gemini-2.5-flash,RESTAURANT_NAME="CloudNest Restaurant",RESTAURANT_ADDRESS="India",INVOICE_LOGO_PATH="/app/data/invoice_logo.png"
```

## 6) Health check
```bash
curl https://YOUR_CLOUD_RUN_URL/healthz
```

## 7) MLOps-lite included
- CI pipeline: `.github/workflows/ci.yml`
- Manual GitHub deploy: `.github/workflows/deploy-cloud-run.yml`
- Cloud Build template: `cloudbuild.yaml`

## 8) Next production upgrades
- Move session state from memory to Redis/Firestore
- Add structured logging + trace IDs
- Add load tests and SLO alerts
