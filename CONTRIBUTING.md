# Contributing to H2AI Chat

Thanks for your interest! Every contribution — code, documentation, bug reports, or ideas — is welcome.

## Before your first code contribution: the CLA

The first time you send a code contribution, an assistant will ask you to **accept the CLA** (Contributor License Agreement) with a single click. It's quick and only needs to be done once.

**In short:** your code **stays yours**, but you give us permission to use it also in the hosted / company edition of the project. That's what lets the project have a business behind it to sustain development, while remaining open. (Full text in `CLA.md`.)

## Getting the project running

Requires **Python 3.11+** (our CI runs on **3.13**). Work inside a **virtual environment** so you don't disturb your global packages:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # runtime + test tools
python -m unittest discover -s execution/tests -v   # run the tests
python -m uvicorn execution.api_server:app --port 8000   # start the app
```

Prefer Docker or a 100%-local setup with your own models? See [`docs/RUN_LOCALLY.md`](docs/RUN_LOCALLY.md).

## Contribution flow

1. Open an **issue** first for large changes (so we can discuss it before you invest time).
2. **Fork** the repo and create a **branch** for your change.
3. **Add or adjust tests** where it makes sense; keep the suite green (a GitHub Action runs the full suite automatically on every PR).
4. Open a **Pull Request** describing the what and the why.
5. Accept the CLA if it's your first time.

## Style

- Small, focused changes; one PR, one thing.
- **Commit messages:** we follow [Conventional Commits](https://www.conventionalcommits.org) — e.g. `feat: add X`, `fix: correct Y`, `docs: …`. It keeps the history readable.
- We don't enforce a code formatter or linter yet — just **match the style of the surrounding code**.
- Be kind in reviews (see `CODE_OF_CONDUCT.md`).

## Security

Found a security issue? **Don't open a public issue** — follow `SECURITY.md`.
