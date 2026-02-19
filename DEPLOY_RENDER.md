# Deploy CloudNest RAG on Render (Free Tier)

## 1) Push your code to GitHub
Make sure your latest project is in a GitHub repository.

## 2) Create service in Render
1. Go to Render dashboard.
2. Click `New +` -> `Blueprint`.
3. Select your GitHub repo.
4. Render will detect `render.yaml`.

## 3) Set secret environment variable
In Render service settings, add:
- `GEMINI_API_KEY` = your Gemini API key

`MODEL_NAME` and other defaults are already in `render.yaml`.

## 4) Deploy
Click deploy. After build finishes, open the service URL:
- `https://<your-service-name>.onrender.com`

## 5) Verify
1. Open app URL.
2. Select order type, slot, preference, place order.
3. Confirm PDF invoice download works.

## Notes
- Free services may sleep when idle; first request can be slow.
- Do not use `--reload` in production (already configured correctly).
