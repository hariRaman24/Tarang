# TARANG — Render-ready deployment

This package runs the frontend and FastAPI backend as **one web service**.

## 1. Test locally

From the project root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

You do **not** need a second frontend terminal in this deployment version.
FastAPI serves the website itself.

Useful endpoints:

```text
/                  TARANG website
/api/status        lightweight service status
/api/health        platform/source metadata
/api/query         marine query API
/docs              FastAPI interactive docs
```

## 2. Put it on GitHub

Create an empty GitHub repository, then from this project root:

```powershell
git init
git add .
git commit -m "Deploy TARANG"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/tarang.git
git push -u origin main
```

Do **not** commit a `.env` file or your Gemini API key.

## 3. Deploy on Render

1. Open Render.
2. Choose **New → Blueprint** if you want Render to read `render.yaml`, or **New → Web Service** for manual setup.
3. Connect the GitHub repository.
4. If using manual setup, use:

```text
Runtime: Python 3
Build Command: pip install -r backend/requirements.txt
Start Command: cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health Check Path: /api/status
```

5. Add environment variable:

```text
GEMINI_API_KEY=<your Gemini API key>
```

Optional:

```text
GEMINI_MODEL=gemini-3.6-flash
```

6. Deploy.
7. Render will provide a public URL similar to:

```text
https://tarang-marine-intelligence.onrender.com
```

## 4. Gemini behavior

When `GEMINI_API_KEY` is present, TARANG uses Gemini for structured query planning.
If Gemini is unavailable, the deterministic planner remains as a fallback.

Gemini does **not** replace official marine sources or the deterministic risk engine.

## 5. Presentation checklist

Before the presentation:

- Open the Render URL several minutes early.
- Run one query to wake a free Render service if it has spun down.
- Test Chennai and one second coastal location.
- Keep a screenshot/video backup in case an upstream INCOIS/IMD service is temporarily unavailable.
- Do not describe TARANG as navigation-grade.

## 6. Updating TARANG after deployment

Edit backend/frontend code locally, then:

```powershell
git add .
git commit -m "Improve TARANG"
git push
```

A Git-connected Render service can redeploy the new version automatically.
