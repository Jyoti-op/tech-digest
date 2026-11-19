# Tech Digest

A small, dependency-free (Python 3.10+ standard library only) tech newsletter system.
See [DESIGN.md](DESIGN.md) for the architecture.

## Run it

```bash
python main.py subscribe demo@example.com --topics AI,Dev,Security
python main.py run --force          # fetch → rank → write output/digest_*.html
python main.py list
python main.py unsubscribe demo@example.com
```

Open the generated file in `output/` in a browser to see the email.

In VS Code: open the **Run and Debug** panel (Ctrl+Shift+D) and pick
"Digest: subscribe demo user", then "Digest: run (preview HTML)".

## Really send email (on your PC)

1. Create a Gmail **App Password**: <https://myaccount.google.com/apppasswords>
   (it needs 2-Step Verification turned on).
2. Copy `.env.example` to `.env` and fill in `DIGEST_SMTP_USER` and `DIGEST_SMTP_PASSWORD`.
   `.env` is git-ignored.
3. Check it: `python main.py test-email yourname@gmail.com`
4. Send: `python main.py run --send --force`

## Run daily in the cloud (GitHub Actions, free)

The workflow in `.github/workflows/digest.yml` runs every day at 06:00 UTC
(07:00 Western Europe in winter, 08:00 in summer; change the `cron` line to move it).

1. Create a **private** repository on GitHub and push this folder to it.
2. In the repo: **Settings → Secrets and variables → Actions → New repository secret**, add:
   | Secret | Value |
   |--------|-------|
   | `DIGEST_SMTP_USER` | your Gmail address |
   | `DIGEST_SMTP_PASSWORD` | the Gmail app password |
   | `DIGEST_SUBSCRIBERS` | `you@gmail.com\|MCP,Automation,HuggingFace,AI\|daily` (separate people with `;`) |
3. **Actions → Daily Tech Digest → Run workflow**, with *force* ticked, sends one right away.

The run history (which stories each person already got) lives in the Actions cache,
not in the repo, and subscriber emails live only in the secret.

Use the cloud *or* a local schedule, not both, or you'll get two emails.

## Sources

| Topic | Sources |
|-------|---------|
| MCP | Official MCP Registry (new servers matching automation keywords), new GitHub MCP repos, `modelcontextprotocol/servers` releases, trending Hugging Face MCP Spaces |
| Automation | Hermes Agent (`NousResearch/hermes-agent`) releases, new GitHub agent/automation repos, Hacker News searches (MCP, Hermes Agent, n8n, AI automation) |
| HuggingFace | Hugging Face blog, HF Daily Papers, HF trending models |
| General tech | Hacker News front page, The Verge, Ars Technica, TechCrunch, GitHub Blog |

Every story gets a short summary: from the feed itself, or from the article page's description.

GitHub search allows only a few anonymous requests per minute. If you see `rate limit exceeded`,
set a GitHub token (no permissions needed): `$env:GITHUB_TOKEN = "..."`.

## Customize
- Sources, weights and topic keywords live in `config.json`.
- `run` only sends stories a subscriber hasn't received before (`deliveries` table),
  and respects daily/weekly frequency unless `--force` is passed.
