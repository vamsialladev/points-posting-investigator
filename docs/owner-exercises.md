# Owner exercises

The owner's answers to each milestone's exercise (spec Part N), kept verbatim.

## Milestone 1 (2026-11-16)
**Exercise:** run `scripts\leaks.ps1` before and after creating `.env`, and explain why the first run fails even
though nothing leaked.

**Owner's result:** NOT RUN before `.env`; after, "7 secret values against 45 tracked files: 0 leaks".

**Owner's answer:** "With no .env the scanner checks nothing, and a check that checks nothing must fail as NOT RUN
rather than pass, otherwise green would claim safety that was never verified, the bug Stage 9's scanner had."

**Note:** correct, and it is ADR-0007's reason. The same holds for gitleaks, which exits 0 on a repository with no
commits (verification log, M1 #13).
