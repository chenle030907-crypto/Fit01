## Deploy Configuration (configured by /setup-deploy)
- Platform: Railway
- Production URL: (set after first deploy)
- Deploy workflow: auto-deploy on push to main
- Deploy status command: HTTP health check at production URL
- Merge method: direct push
- Project type: Web app (Flask + SQLite)
- Post-deploy health check: GET /

### Deploy hooks
- Pre-merge: none
- Deploy trigger: automatic on push to main
- Health check: production URL /

### Environment Variables
- `AI_API_KEY`: DeepSeek API key for food parsing and recommendations
- `DATA_DIR`: Path to persistent volume for SQLite database (default: app directory)

### Railway Setup Steps
1. Go to railway.app → New Project → Deploy from GitHub
2. Select chenle030907-crypto/Fit01 repo
3. Add environment variable: `AI_API_KEY` = your DeepSeek API key
4. Add volume mount: path `/data` → `DATA_DIR` = `/data`
5. Deploy
