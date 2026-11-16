# Role coverage map

One row per role from the purpose lens 11 (Stage 9's `docs/project-purpose.md`). **A role is "Shown" only with real
evidence in this repo.** At Milestone 1 the only evidence is setup and documentation, so most roles are Planned.

Columns follow Stage 9: Role | Evidence in the repo | Milestone | Status | Questions this role would ask (and where the
answer lives).

| Role | Evidence in the repo | Milestone | Status | Questions this role would ask (and where the answer lives) |
|---|---|---|---|---|
| Forward Deployed Engineer / Solutions Engineer | `docs/discovery.md` (fictional stakeholders, RACI, AI vs rules), `docs/workflow.md`, `docs/continuity.md` | 1 | Shown (discovery only; integration, demo and handover planned M2, M16, v2) | Who owns each step today? (`docs/discovery.md` §2, §8) · What stays deterministic? (§9) · How does this tie to Stage 9? (`docs/continuity.md` §3) |
| AI / Applied AI Engineer | – | 6 | Planned (M6) | Which tools can the model call? · What stops the loop? · How are citations checked? |
| ML Engineer / Applied Scientist | – | 3, 9 | Planned (M3) | What was pre-registered? · How are splits grouped? · Is the difference larger than the noise? |
| MLOps / LLMOps Engineer | – | 6, 9 | Planned (M6) | Where are prompts versioned? · How is cost capped? · What gates a prompt change? |
| Data Engineer | – | 2 | Planned (M2) | Where is the schema registry? · How are schemas evolved? · How do synthetic shapes match Stage 9? |
| Backend / Platform Engineer | – | 2, 7 | Planned (M2) | Where can duplicates occur? · How does the outbox stay consistent? · What happens on crash mid-processing? |
| Site Reliability Engineer | – | 4, 7, 14 | Planned (M4) | Does every alert have an owner and a runbook? · How is a replay verified? · What did the game day show? (v2) |
| Security Engineer | `.claude/settings.json`, `app/preflight.py`, `app/env_leaks.py`, `scripts\secrets_scan.ps1`, `.pre-commit-config.yaml` | 1 | Shown (secrets hygiene only; threat model planned M6–8) | How are secrets kept out of output? (`tests/test_preflight.py::test_output_never_contains_values`) · What if a scanner checks nothing? (ADR-0007) · Can log text steer the AI? (M6) |
| Solutions / Enterprise Architect | – | 2 | Planned (M2) | What swaps for the real PMS and ledger? (`docs/real-system-swap-guide.md`, M2) |
| Staff / Principal Engineer | `docs/decisions.md` (ADR-0001 to ADR-0007, options and what would change each) | 1 | Shown (decision records only; strategy, scaling, TCO planned M2) | Why port instead of share code? (ADR-0003) · Why v1 first? (ADR-0002) |
| Engineering Manager / Tech Lead | `docs/implementation-plan.md`, `docs/requirements-matrix.md`, `docs/implementation-status.md` | 1 | Shown (plan and tracking) | What's in v1? (`docs/implementation-plan.md` §1) · What's blocked on the owner? (`docs/session-handoff.md`) |
| Product Manager | `docs/discovery.md` §5 (success metrics), §6–7 (scope, exclusions) | 1 | Shown (framing only) | What does success look like? (§5) · What are we not building? (§7) |
| Technical Program Manager | `docs/requirements-matrix.md` (release and milestone per requirement) | 1 | Shown (tracking only) | Which milestone delivers X? (matrix) · What depends on the owner? (`docs/session-handoff.md`) |
| QA / Test Engineer | `tests/required_markers.py`, `tests/test_required_markers.py`, `scripts\test.ps1` | 1 | Shown (test-guard only; integration and Playwright planned M2, M8) | Can a green run hide skipped tests? (ADR-0007) · Where is the end-to-end test? (M8) |
| Customer Success / Support Lead | – | 8, 15 | Planned (M8) | How does support learn which members were affected? (M8) · Where are UAT scripts? (v2) |
| Responsible AI / Governance | – | 6, 12 | Planned (M6) | What can the AI never do? · How is human oversight enforced? · What residual risks remain? |
| Executive sponsor | – | 3 | Planned (M3) | One page: outcome, evidence, risks, cost (`docs/executive-brief.md`, end of M3) |
