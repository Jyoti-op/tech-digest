# TechPulse

AI-powered weekly technology briefing, delivered **every Saturday at 10:00 (Europe/Berlin)**.
Standard-library Python only, free to run. See [DESIGN.md](DESIGN.md) for the original architecture.

**Topics:** MCP · AI · Automation · Dev · Data Engineering · Cloud/DevOps · Dev Tools · Emerging

Each issue has 7–10 updates. Each update includes:
- **Short summary**
- **How it works:** a technical explanation
- **Why it matters**
- **Key takeaways**
- **Learn more:** learning resources

The issue starts with the week's highlights and ends with a **Weekly technology takeaway**.

## Free AI write-ups (no API key)

| Where it runs | Provider used | Cost |
|---|---|---|
| GitHub Actions (the weekly job) | **Ollama + Llama 3.2 (3B)** running inside the job, so no account or key | Free |
| Your PC, no keys | Extractive fallback: summary plus explanation from the article's own sentences | Free |
| Your PC with [Ollama](https://ollama.com) running | picked automatically (`ollama pull llama3.2:3b`) | Free (local) |
| Optional, paid | `AI_PROVIDER=openai` + `OPENAI_API_KEY`, or `AI_PROVIDER=claude` + `ANTHROPIC_API_KEY` (`pip install anthropic`) | Pay per use |

The AI uses only the article text; learning links must come from the article itself, so no made-up URLs.
If the AI fails or hits a rate limit, that story falls back to the free extractive write-up.
Write-ups are cached in the database, so each story is processed once.

## Run it

```bash
python main.py subscribe you@example.com                  # all 8 topics, weekly
python main.py subscribe you@example.com --topics "MCP,AI,Data Engineering"
python main.py run --force                                # build a preview in output/
python -m unittest discover -s tests                      # run tests
```

## Email and the cloud

- Gmail login: `.env` locally (see `.env.example`), GitHub secrets in the cloud
  (`DIGEST_SMTP_USER`, `DIGEST_SMTP_PASSWORD`, `DIGEST_SUBSCRIBERS`).
- `DIGEST_SUBSCRIBERS` format: `you@gmail.com||weekly` for all topics, or `you@gmail.com|MCP,AI|weekly`;
  separate people with `;`.
- `.github/workflows/digest.yml` fires Saturday at 08:00 and 09:00 UTC. The app only sends when it is
  10:00 in Berlin, which handles summer and winter time.
- Send one now: **Actions → Weekly TechPulse → Run workflow** (tick *force*).

## Sources

| Topic | Sources |
|---|---|
| AI | OpenAI News, Google DeepMind, Hugging Face blog and trending models, HN (Anthropic, Claude, OpenAI) |
| MCP | MCP Registry (new automation servers), new GitHub MCP repos, MCP servers releases |
| Automation | Hermes Agent releases, GitHub agent/automation repos, HN (agents, n8n) |
| Dev | Python blog, plus keyword-matched stories |
| Data Engineering | Databricks, dbt, Confluent, Apache News |
| Cloud/DevOps | AWS News, Kubernetes, Docker, Cloudflare |
| Dev Tools | GitHub Blog, VS Code, JetBrains |
| Emerging | MIT Technology Review, HF Daily Papers |

Add or remove sources, weights and keywords in `config.json`.

## Not built yet (from the TechPulse proposal)
PostgreSQL + SQLAlchemy/Alembic (still SQLite), FastAPI endpoints, Resend, Docker.
