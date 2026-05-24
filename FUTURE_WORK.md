# FUTURE_WORK.md

Items intentionally **out of scope** for the Sunday 2026-05-24 demo. Parked here per the scope-discipline rule in [CLAUDE.md](CLAUDE.md). New ideas mid-build go here too — not into the build.

Reviewed and pruned after the demo ships.

---

## UX

- **Desktop side-by-side chart layout** — always-stacked vertical layout was chosen for Sunday so one layout works on both desktop and phone. Side-by-side on desktop ≥1280px is a polish item.
- **True row-streaming via `st.empty()`** — two-phase render (badges first, AI synthesis fills in) was chosen instead because it's simpler. Per-row streaming is more responsive but adds state-management complexity.
- **Mobile-specific scan-table layout** (card list instead of `st.dataframe`) — only if real-device testing during build reveals `st.dataframe` mobile UX is unusable.
- **Auto-refresh on a timer** — manual refresh only for Sunday. Optional 5-minute auto-refresh during market hours later.
- **"Pin multiple tickers for comparison" view** — only one pinned ticker at a time for Sunday.
- **Onboarding tutorial / first-time-user tour** — the "How this works" expander is the Sunday version. Could become a tour later.
- **Per-ticker historical pattern view** — see how patterns evolved through the week.

## Data & analytics

- **Put/call IV skew chart in the pinned card** (deferred from product-review item #5b, 2026-05-23). Useful for directional weekly trades. Adding it would push the pinned card to 4 stacked charts — meaningful mobile-UX cost. Logged for v0.2.
- **More than 30 tickers** — current hard cap. Lifting it requires UI for filtering/sorting at scale.
- **WebSocket / true real-time updates** — UW Basic tier doesn't support WebSocket. Requires tier upgrade.
- **Historical pattern detection beyond 30 days** — requires UW Pro tier.
- **Custom pattern definitions via UI** — currently the four theses are code-defined.
- **Backtest mode** — explicitly excluded per CLAUDE.md "no predictions / no edge claims," but could be added as a separate "research" page that respects the framing.

## Infrastructure

- **GitHub Actions CI** — local `uv run pytest` only for Sunday.
- **Scheduled live schema-drift checks** (cron-running `pytest -m live`) — manual on-demand only.
- **Custom domain** — default `*.streamlit.app` for Sunday.
- **Multi-environment** (staging vs prod) — single prod-only for Sunday.
- **Container / Docker deploy** — Streamlit Cloud handles deploy.
- **Migration off Streamlit Cloud** — only if scale demands it.
- **Auth on the public URL** — currently personal-use license framing; if scope shifts to multi-user, auth is required.
- **Pre-commit hook for `requirements.txt` sync** — manual `scripts/sync_requirements.sh` for Sunday.

## Observability

- **Sentry-style error telemetry** — `print()` and Streamlit's built-in error display only for Sunday.
- **Per-call cost tracking dashboard** — session-level counter only for Sunday.
- **Test coverage reporting** — fixture-based tests only, no coverage gating.
- **Mutation testing** — not for Sunday.

## Quality

- **Streamlit rendering tests** — Playwright excluded per CLAUDE.md; investigate `streamlit.testing.v1.AppTest` if needed later.
- **End-to-end click-flow tests** — manual verification only for Sunday.
- **Accessibility audit** (axe-core, screen-reader testing) — basic text-not-color-only handled in Sunday; deeper a11y is post-demo.

## Multi-LLM

- **Anthropic Claude as alternative synth provider** — Gemini Flash Lite chosen for Sunday. Multi-LLM fallback could be added but adds branching complexity in the synth layer.
- **Model A/B testing** for synthesis quality — not for Sunday.
