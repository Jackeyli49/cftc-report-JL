# Automated English CFTC Positioning Report

This is a static English dashboard that updates from official CFTC files every week.

## What is automated

- GitHub Actions runs after the normal Friday CFTC release.
- A second Saturday run catches delayed releases or temporary download failures.
- The updater downloads official Disaggregated Futures Only and Traders in Financial Futures data.
- It calculates weekly changes, open-interest-normalized 156-week z-scores, positioning actions and crowding signals.
- It commits `data/reports.json`; Vercel or Netlify then redeploys automatically.

## One-time setup (no coding)

1. Create a free GitHub account.
2. Create a new **public or private repository**.
3. Upload every file and folder from this package. Make sure the hidden `.github` folder is included.
4. Open the repository's **Actions** tab and enable workflows if GitHub asks.
5. Open **Update CFTC data**, then click **Run workflow** once.
6. Connect the GitHub repository to Vercel and deploy it as a static site. No build command is required.
7. Future updates happen automatically. Each successful data commit triggers a new deployment.

## Important limitation

The automatic feed is official CFTC positioning data. Price changes are shown as `—` because CFTC does not publish futures settlement prices in the COT files. Adding automatic market prices requires a separate licensed or third-party price source.

## Schedule

The workflow runs Friday at 22:17 UTC and retries Saturday at 10:17 UTC. CFTC normally releases Friday at 3:30 p.m. Eastern Time, but holidays can delay publication.

## Manual update

GitHub → Actions → Update CFTC data → Run workflow.
