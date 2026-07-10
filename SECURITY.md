# Security Policy

## Reporting a vulnerability

If you think you've found a security issue, **please don't open a public issue** or discuss it in forums.

- **Preferred:** open a private report through **GitHub Security Advisories** for this repository (the repo's *Security* tab → *Report a vulnerability*). It's an isolated, private channel — ideal for detailed proof-of-concepts.
- **Or** email us at **h2aichat.com@gmail.com**. Note that plain email is not end-to-end encrypted, so for sensitive details please prefer the advisory above.

If you can, include: which version, how to reproduce it, and the impact you believe it has. **We aim to acknowledge your report within 3 business days** and will keep you posted on the fix. We appreciate responsible disclosure and will credit you if you'd like.

## Scope

**In scope:** vulnerabilities in **this project's own code** — authentication and tokens, the API, the orchestration engine, and how we handle data.

**Out of scope** (please don't report these here):

- Vulnerabilities in **third-party dependencies** — we track those automatically (see *Automated checks*); report them to the upstream project.
- **Denial-of-service or volumetric attacks** against the hosted site.
- Issues that require an already-compromised machine, physical access, or social engineering.

## Safe harbor

We will not pursue or support legal action against anyone who reports a vulnerability in **good faith**, respects the privacy of other people's data, avoids destructive or disruptive testing, and follows this policy. If you're unsure whether something is allowed, ask us first.

## Supported versions

We provide security support for the **latest released version**. As a young project, we don't yet maintain older release branches.

## Automated checks

Our CI runs **`pip-audit`** against our Python dependencies, so known-vulnerable packages get flagged automatically.

## Good practices when deploying

- Never commit real keys to the repository; use environment variables (see `.env.example`).
- If you use local models for confidential data, use **models from recognized sources** and avoid enabling "trust remote code" from unknown authors.
