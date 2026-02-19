param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $false)]
    [string]$Region = "asia-south1",

    [Parameter(Mandatory = $false)]
    [string]$ServiceName = "cloudnest-rag",

    [Parameter(Mandatory = $false)]
    [string]$RuntimeServiceAccount = "",

    [Parameter(Mandatory = $false)]
    [string]$GeminiSecretName = "gemini-api-key"
)

$ErrorActionPreference = "Stop"

Write-Host "[1/6] Setting project..." -ForegroundColor Cyan
gcloud config set project $ProjectId | Out-Null

if (-not $RuntimeServiceAccount) {
    Write-Host "Runtime service account not provided. Using default Compute Engine service account..." -ForegroundColor Yellow
    $ProjectNumber = (gcloud projects describe $ProjectId --format="value(projectNumber)").Trim()
    $RuntimeServiceAccount = "$ProjectNumber-compute@developer.gserviceaccount.com"
}

Write-Host "[2/6] Enabling required APIs..." -ForegroundColor Cyan
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com | Out-Null

Write-Host "[3/6] Checking secret '$GeminiSecretName'..." -ForegroundColor Cyan
$secretExists = $true
try {
    gcloud secrets describe $GeminiSecretName | Out-Null
} catch {
    $secretExists = $false
}

if (-not $secretExists) {
    throw "Secret '$GeminiSecretName' not found. Create it first with your Gemini API key."
}

Write-Host "[4/6] Granting secret access to runtime service account..." -ForegroundColor Cyan
gcloud secrets add-iam-policy-binding $GeminiSecretName `
    --member="serviceAccount:$RuntimeServiceAccount" `
    --role="roles/secretmanager.secretAccessor" | Out-Null

Write-Host "[5/6] Building container image..." -ForegroundColor Cyan
gcloud builds submit --tag "gcr.io/$ProjectId/$ServiceName"

Write-Host "[6/6] Deploying to Cloud Run..." -ForegroundColor Cyan
gcloud run deploy $ServiceName `
    --image "gcr.io/$ProjectId/$ServiceName" `
    --region $Region `
    --platform managed `
    --allow-unauthenticated `
    --service-account $RuntimeServiceAccount `
    --set-secrets "GEMINI_API_KEY=$GeminiSecretName:latest" `
    --set-env-vars "MODEL_NAME=gemini-2.5-flash,RESTAURANT_NAME=CloudNest Restaurant,RESTAURANT_ADDRESS=India,INVOICE_LOGO_PATH=/app/data/invoice_logo.png"

$serviceUrl = (gcloud run services describe $ServiceName --region $Region --format="value(status.url)").Trim()
Write-Host "Deployment complete." -ForegroundColor Green
Write-Host "Service URL: $serviceUrl" -ForegroundColor Green
Write-Host "Health check: $serviceUrl/healthz" -ForegroundColor Green
