# Contributing to H2AI Chat

Thanks for your interest! Every contribution — code, documentation, bug reports, or ideas — is welcome.

## Before your first code contribution: the CLA

The first time you send a code contribution, an assistant will ask you to **accept the CLA** (Contributor License Agreement) with a single click. It's quick and only needs to be done once.

**In short:** your code **stays yours**, but you give us permission to use it also in the hosted / company edition of the project. That's what lets the project have a business behind it to sustain development, while remaining open. (Full text in `CLA.md`.)

## Getting the project running

```bash
pip install -r requirements-dev.txt   # runtime + test tools
python -m unittest discover -s execution/tests -v   # run the tests
python -m uvicorn execution.api_server:app --port 8000   # start the app
```

## Contribution flow

1. Open an **issue** first for large changes (so we can discuss it before you invest time).
2. **Fork** the repo and create a **branch** for your change.
3. **Add or adjust tests** where it makes sense; keep the suite green.
4. Open a **Pull Request** describing the what and the why.
5. Accept the CLA if it's your first time.

## Style

- Small, focused changes; one PR, one thing.
- Be kind in reviews (see `CODE_OF_CONDUCT.md`).

## Security

Found a security issue? **Don't open a public issue** — follow `SECURITY.md`.
