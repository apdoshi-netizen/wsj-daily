# WSJ Daily — setup

A daily 9:00 AM ET email with 4 curated, **direct-link** WSJ articles
(Macro / Industry-Company-Transaction / Op-Ed / Tech).

## How it works

- **GitHub Actions** runs every morning on GitHub's servers (a non-Google IP —
  this matters, see note): `generate.py` fetches live WSJ headlines, the Claude
  API picks the best per slot + writes a one-line summary, each pick is resolved
  to its **direct wsj.com URL**, and `picks.json` is committed to your repo.
- **Google Apps Script** runs at 9:00 AM ET: reads `picks.json` from your repo's
  raw URL and emails the digest to everyone in the recipients Doc.

> Why two systems: only a non-Google IP can turn Google News links into direct
> wsj.com URLs (Google CAPTCHA-blocks its own Apps Script IPs). GitHub Actions
> does the fetching/resolving; Apps Script only reads a plain file + sends mail.

## Files (in this folder)

- `generate.py` — the generator (runs in GitHub Actions).
- `.github/workflows/daily.yml` — the daily schedule + commit step.
- `mailer.gs` — the Google Apps Script mailer.

---

## Part A — GitHub (generation)

1. **Create a repo.** On github.com → New repository, e.g. `wsj-daily`.
   **Public** is simplest (contents are just headlines + links). If you want it
   private, tell me — Apps Script then needs a token to read the raw file.

2. **Add the files.** Put `generate.py` at the repo root and
   `.github/workflows/daily.yml` at that path. (Upload via the web UI or push
   from this folder.)

3. **Add your Claude API key as a secret.** Repo → Settings → Secrets and
   variables → Actions → **New repository secret**:
   - Name: `ANTHROPIC_API_KEY`
   - Value: `sk-ant-...` (from console.anthropic.com; you have credit)

4. **Run it once manually.** Repo → **Actions** tab → enable workflows if
   prompted → "WSJ Daily picks" → **Run workflow**. After ~1 min a `picks.json`
   commit appears in the repo. Open it — you should see today's date and 4
   `wsj.com` links.
   - In the run log, the generate step prints `curation: Claude` (good) or
     `curation: heuristic fallback (...)` — if it says heuristic, the API key or
     billing has an issue; fix and re-run.

5. **Note your raw URL:**
   `https://raw.githubusercontent.com/<you>/<repo>/main/picks.json`

## Part B — Google Apps Script (sending)

1. <https://script.google.com> → **New project**, paste all of `mailer.gs`.
2. In `CONFIG`, set **`PICKS_URL`** to your raw URL from A-5.
3. Project Settings (gear) → **Time zone** → `America/New_York`.
4. Select **`sendTestNow`** → **Run**, authorize when prompted. Check your inbox
   for `[TEST] WSJ — <date>` and click a link to confirm the WSJ article opens.
5. Select **`installTrigger`** → **Run**. Live — sends daily ~9:00 AM ET.

## Everyday use

- **Add/remove recipients:** edit the **WSJ-FT Recipients** Google Doc
  (one email per line). Nothing else. (Doc is already wired into `mailer.gs`.)
- **See today's picks without waiting:** open `picks.json` in the repo, or run
  the GitHub workflow manually.
- **Pause:** Apps Script → Triggers (clock icon) → delete the `sendDaily`
  trigger. Re-run `installTrigger` to resume.
- **Change send time:** edit `SEND_HOUR` in `mailer.gs`, re-run `installTrigger`.

## Timing & reliability

- Generation runs 11:30 UTC (~6:30 AM EST / 7:30 AM EDT); send is 9:00 AM ET —
  a wide buffer even if GitHub's cron lags (it can start ~10–15 min late).
- If a morning's generation ever fails, `picks.json` keeps yesterday's date, and
  the mailer (which requires today's date) sends a one-line "no digest today"
  note instead of stale news.
- Weekends: WSJ publishes less, so some slots may be a day old — that's WSJ's
  cadence, not a fault. Weekdays are same-day.

## Notes

- The old **WSJ-FT Daily** Drive folder now only serves the **recipients Doc**;
  any `picks-*.json` files still in it are unused (the mailer reads GitHub now).
- Your Anthropic API key lives only in the GitHub secret — not in Apps Script.
