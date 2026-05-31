## Deploy Configuration (configured by /setup-deploy)
- Platform: Render
- Production URL: (set after first deploy)
- Deploy workflow: auto-deploy on push to main (via render.yaml Blueprint)
- Deploy status command: HTTP health check at production URL
- Merge method: direct push
- Project type: Web app (Flask + SQLite)
- Post-deploy health check: GET /

### Environment Variables
- `AI_API_KEY`: DeepSeek API key for food parsing and recommendations (set in Render dashboard)
- `DATA_DIR`: `/data` — persistent disk for SQLite

### Render Setup Steps
1. Go to dashboard.render.com → New → Blueprint
2. Connect chenle030907-crypto/Fit01 repo
3. Render reads render.yaml automatically
4. Set AI_API_KEY env var in the web service dashboard
5. Deploy
