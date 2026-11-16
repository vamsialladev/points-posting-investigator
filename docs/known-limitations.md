# Known limitations

Kept current at every milestone. Each line says what is limited, why, and what would change it.

## As of Milestone 1 (2026-11-16)
- **No product yet.** Only the setup, guidance, tracking, fictional discovery and the preflight command exist. Every
  pipeline, investigator, recovery and benchmark requirement is `Planned`.
- **The discovery is fictional.** Stakeholders, interview excerpts, volumes and costs are simulated and labelled.
  The pain points are hypotheses (DH1–DH6) to measure in the benchmark, not findings.
- **Preflight checks format, not validity.** It catches empty values, typos and wrong shapes (for example a key
  without `sk-ant-`). It can't tell whether a key is revoked or has spend left; a live smoke test (only with the
  owner's approval) does that.
- **The project1-wide deny rules also block `.env.example`** (ADR-0008): `.env.*` matches it in every project under
  project1, so Claude Code can't read or edit any template there. Waiting on the owner's choice to keep that or name
  the variants instead.
- **Shell deny rules match command text, not file access.** A reader not on the list, or a script that opens the file
  itself, isn't blocked. They guard against mistakes; they are not a sandbox.
- **The deny rules were observed in this session only,** which loaded them right after they were written. A fresh
  session started in `C:\projects\project1` is the owner's confirming check (`docs/session-handoff.md`).
- **No GitHub Actions yet.** The public repo exists (2026-11-16), but CI arrives in M2; until then the checks are local
  (`scripts\ci_local.ps1`), so "merge when CI is green" can't apply to a PR yet.
- **`scripts\leaks.ps1` reports NOT RUN until `.env` exists.** That is by design (ADR-0007), not a fault.
- **The Makefile is untested on the owner's machine**, which has no `make`. The `scripts\*.ps1` twins are what ran.
- **No independent review.** The continuity review, the matrix and the discovery were written by Claude Code from
  the live site and the repos. Nobody else has reviewed them yet.
- **Coverage gate is on `app/` only,** which holds only preflight and the leak scanner for now. It widens as packages
  are added.
