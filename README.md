# FlowAlpha Simple

A zero-maintenance English CFTC positioning dashboard.

## Deploy
Vercel detects `package.json`, runs `npm run build`, and serves `dist/`.

## Automatic updates
GitHub Actions downloads official CFTC historical compressed files every Friday night and retries Saturday morning. It commits `data/reports.json`; Vercel then redeploys automatically.

## First run
GitHub → Settings → Actions → General → Workflow permissions → Read and write permissions.
Then Actions → Update CFTC data → Run workflow.
