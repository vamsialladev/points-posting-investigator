# Continuity review: how Stage 10 fits the existing engagement

**Status:** Implemented and verified (read-only review, 2026-11-16). Requirement P0-16.

The owner's instruction: vamsialla.com and the public repositories under github.com/vamsialladev are the source of
truth. Where they differ from `docs/MASTER-SPEC.md`, this file follows them and records the difference (§9). This
review builds on Stage 9's own continuity review (`loyalty-support-modernization/docs/continuity.md`, 2026-10-28). It
re-checks what may have changed, and does not repeat what still holds.

## 1. Sources reviewed (2026-11-16)
| Source | How | Version |
|---|---|---|
| vamsialla.com `data/projects.json` | fetched with a cache-busting query, compared with the site repo's local `main` | **identical** (8,363 bytes) to `vamsialladev.github.io` at `7a2cfe7` (2026-10-28) |
| `loyalty-support-modernization` (Stage 9) | read-only local checkout + `git ls-remote` | local `main` at `7047590` (Milestone 12 close-out); remote `HEAD` `a1d7f93` |
| Stage 9 docs read in full | `CLAUDE.md`, `docs/project-purpose.md`, `docs/continuity.md`, `docs/known-limitations.md`, `docs/session-handoff.md` (current part) | as above |
| Stage 9 patterns | read-only exploration of `app/preflight.py`, `app/env_leaks.py`, `scripts/*.ps1`, `.github/workflows/ci.yml`, RFC-0001, `app/domain/approval_binding.py`, benchmark files, tracking files | as above |
| Other public repos | `git ls-remote … HEAD` | `hotel-ai-discovery` `e502e2b`, `hotel-ops-assistant` `dd01234`, `guest-request-agent` `cfe4ace`, `eval-harness` `ccbdcd4`, `hotel-ai-handoff` `35c7ad1`, `resort-activities-concierge` `711803c`, `hotel-tools-mcp` `3e3e700`, `hotel-ops-analytics-agent` `270765e`, `fde-account-research-agent` `967930f`, `hotel-ai-platform` `9fb8746`, `agent-protocols-lab` `2f6fea6` |
| GitHub account | `gh repo list vamsialladev` | 16 repositories, 15 public; **no `points-posting-investigator` repo yet** |

No existing repository was modified.

## 2. The engagement as published today
`data/projects.json` lists stages PS, 0–8: PS, 1, 2, 3, 4, 5, 6, 7 and 8 are `Live`; 0 is `Published`.

- **Stage 9 is not on the site yet.** It is public on GitHub, built through its Milestone 12, and not deployed: its
  handoff waits for the owner's "go" on Cloud Run.
- So Stage 10's card can only follow Stage 9's. The Stage 10 site PR (M16) must come after, or with, Stage 9's.

The engagement sentence stays: "One independent, simulated engagement for a fictional hotel group with two properties
and synthetic data."

## 3. Storyline: what Stage 9 handed to Stage 10
Stage 9's backlog has a table "Owned by Stage 10 (a separate future project; not built here)":

| Item | Stage 9's only touch point |
|---|---|
| Kafka / event-driven posting pipeline | "Stage 9 may note that some missing-points root causes are posting-pipeline failures; Stage 10 investigates them" |
| Incident investigation and AIOps over telemetry | "Stage 9 emits OpenTelemetry traces Stage 10 could consume" |

Stage 9's root-cause analysis names two defects that start in the posting pipeline:
- **D24 "Upstream stay record genuinely missing"** (1.5% of its synthetic history): "The property never transmitted
  the stay (posting-pipeline failure, Stage 10's territory)."
- **D06 "Late ledger postings beyond the waiting period"** (2%): "Batch posting retries after a property interface
  outage."

These two give Stage 10 its "why". Stage 10's scenarios cover the mechanisms that produce them:
- stays never posted: schema break, poison message, outbox stopped
- postings that land late: timeouts, rate limits, lag, retries

Each Stage 10 incident produces an affected-member list Stage 9's cases can be matched against. Those Stage 9
percentages describe Stage 9's own synthetic history (its own limitation: "the history restates our assumptions"),
so Stage 10 cites them as the storyline, never as evidence.

## 4. Hotel group, properties, loyalty program (unchanged; Stage 10 reuses them)
- **Hotel group:** unnamed "fictional hotel group", tenant ID `hg-demo`.
- **Properties:** `beach-resort` (Beach Resort) and `mountain-lodge` (Mountain Lodge). Stay IDs `BR-####` and
  `ML-####`. Stage 9's second customer (Cedarpoint Inns) is not used here.
- **Program:** "Guest Rewards".
  - Tiers: Silver (5+ nights), Gold (15+), Platinum (40+).
  - Earning: **10 points per US dollar on the room rate**; taxes, resort fees and pet fees don't earn.
  - Member numbers: `GR-` plus five digits.
- **Stage 9's ID shapes Stage 10 keeps:** ledger entries `L-0000001`, posting-queue items `Q-000001`, PMS records
  `R-0000001`. Stage 9's `PostingQueueItem` has `item_id`, `member_number`, `stay_id`, `points`, `queued_at_utc`,
  `expected_post_at_utc` and `posts_entry_id`; Stage 10's posting records will map to it (M2,
  `docs/data-dictionary.md`).
- **Waiting period:** Stage 9 added a versioned waiting period before missing-points requests. Stage 10's clock-skew
  scenario (FAIL-13) uses it, so M3 cites Stage 9's policy version.

## 5. Writing, metrics and status conventions (unchanged)
- **Writing:**
  - Plain English, short sentences, first person in narration.
  - Numbers always with counts, denominators, version and date ("99% (167/168)").
  - Failures and corrections reported next to successes.
- **Cards:** exactly three `<dl class="stats">` items; the `<dd>` gives the denominator, runs, held-out result, and
  what a latency figure measures.
- **Cost:** per 1,000 requests. Stage 10's unit is **per 1,000 investigated incidents**, and **$0.00 when mock**.
- **Public statuses:** `Live`, `Published`, `Built`, `Next`, `Planned`. Stage 10 shows `Built` until a live link is
  verified (v2).
- **Internal statuses:** spec 0.3 (`docs/implementation-status.md`).

## 6. Patterns reused from Stage 9 (ADR-0003)
| Pattern | Stage 9 source | Stage 10 | Milestone |
|---|---|---|---|
| Preflight (set / missing / invalid, never a value) | `app/preflight.py`, `tests/test_preflight.py` | `app/preflight.py` (new profiles, ADR-0006) | 1 |
| `.env` deny rules | `.claude/settings.json` | same, plus PowerShell forms | 1 |
| Leak scanner | `app/env_leaks.py` | same, NOT RUN on empty input (ADR-0007) | 1 |
| Skip-becomes-failure guard | `REQUIRE_BROWSER` (`tests/browser/test_legacy_e2e.py`) | `REQUIRE_MARKERS` for any marker (`tests/required_markers.py`) | 1 |
| Local CI | `scripts\ci_local.ps1` `Step()` table | same shape, grows each milestone | 1 → 13 |
| gitleaks from a pinned image | `ghcr.io/gitleaks/gitleaks:v8.30.1` in pre-commit and CI | same, plus a 0-commits check | 1 |
| Tracking formats | matrix, ADR headings, verification log, handoff | same | 1 |
| Purpose lenses and role coverage map | `docs/project-purpose.md`, `docs/role-coverage-map.md` | same lenses, proportionate | 1 → |
| Write path | RFC-0001, `app/domain/approval_binding.py`, `roles.approval_refusal()`, kill-switch row, SKIP LOCKED jobs, append-only audit by role grants | adapted to message-set replay | 7 |
| Pre-registration and freeze | `docs/hypotheses.md` (commit `1f8b8e6`), `tests/test_preregistration.py`, `evaluations/freeze.py` | pre-registration moved to M3, before any arm | 3, 9 |
| Mock vs live separation, NOT_TESTED verdicts | `benchmarks/results/{deterministic,mock,live}/`, `evaluations/decide.py` | same layout | 9 |
| Tracing | `app/observability/tracing.py` (scrubbing exporter), `grafana/otel-lgtm` compose profile | plus Kafka header propagation | 4 |
| Eval Harness export | `evaluations/export_eval_harness.py` | same format; registration in eval-harness is v2 | 9 |
| Wilson intervals | not in Stage 9; `eval-harness/src/hoteleval/` | ported from eval-harness | 9 |
| Video kit | `C:\projects\project1\video-kit` (Kokoro, captions, `numbers_check.py`, `og_render.py`) | same | 16 |

## 7. Facts that shape Stage 10's design
- **eval-harness registration:** its `schema.py` has a fixed `PROJECTS` allowlist and
  `PROPERTIES = ("beach-resort", "mountain-lodge")`. Exporting in its format works without changes. Registering
  Stage 10 is a separate eval-harness PR (BENCH-15, v2).
- **The Stage 9 adapter:**
  - Stage 9's case API (`/api/v1/cases…`) uses a console session cookie plus CSRF, not a bearer token.
  - `CaseCreate` has no flag or tag field; the closest are `POST /cases/{id}/feedback` and its mock customer API's
    `POST /v1/tickets`.
  - So "flag the matching Stage 9 cases" needs a small, reviewed Stage 9 change (AUTO-10, v2). Stage 10 never edits
    Stage 9.
- **Stage 9 has no Kafka or outbox code.** Its architecture records them as "Stage 10 territory". Nothing to reuse;
  Stage 10 builds them (M2).
- **Hosting:** every live app so far is free-hosted (Streamlit Cloud; Stage 7 on Vercel; Stage 9 planned on Cloud Run
  with a $10 spend cap). A Kafka stack doesn't fit those. Cloud options and costs go to the owner in v2 (DEL-08),
  before anything is created.

## 8. README and case-study conventions (for M16)
Unchanged from Stage 9's review §8–9: the README order is `CLAUDE.md` §18; the case study uses numbered sections 01–11
with the demo hero first. Proposed names:
- slug `points-posting-investigator`
- page `projects/points-posting-investigator.html`
- OG image `assets/og-points-posting-investigator.png`
- video `videos/points-posting-investigator-demo.mp4`

## 9. Differences between the spec and the site or repos (site and repos win)
| Topic | Spec says | Site / repos show | Stage 10 follows |
|---|---|---|---|
| Builder | Codex ("How to use (Codex)", Appendix A) | Stage 9 was built with Claude Code, with Codex only as a logged exercise (its `CLAUDE.md`, `AGENTS.md`) | Claude Code; Codex optional (ADR-0001) |
| Narration | "I record myself"; never a synthetic voice imitating me | Videos are "AI-narrated" with a labelled Kokoro voice; the owner's standing rule 9 asks for a labelled generated voice | Labelled generated voice + own-voice script (ADR-0004) |
| Hotel group | "the same fictional hotel group" | Unnamed; tenant `hg-demo` | Unnamed; `hg-demo` |
| Stage 9 cases | "flag the matching Stage 9 missing-points cases" | No flag field in Stage 9's case API | Affected-member list in v1; adapter + Stage 9 PR in v2 |
| Site order | Stage 10 card and "How I work" row | Stage 9 isn't on the site yet | Stage 10's site PR follows Stage 9's |
| Eval Harness | "export to the existing Eval Harness format" | Fixed `PROJECTS` allowlist | Export in v1; registration PR in v2 |
| Logs store | "Loki or Postgres" | Stage 9 kept logs in `docker compose logs`, not Loki | Postgres, so investigator citations point at stored rows (decided in M4) |
| Hypotheses and thresholds | committed "before C is run" (H3) | Stage 9 committed them before any arm code | Before any arm code, in M3 (ADR-0002) |
