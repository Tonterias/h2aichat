# H2AI Chat

**Several AIs debate with each other, and you moderate.** A turn-based conversation system where different models (each with its own role) talk, challenge one another, and contrast ideas — while a human moderates. **Self-hostable, and you can run it with your own local models, so your data never leaves your machine.**

There's evidence that simulated debate between opposing perspectives **improves the quality of reasoning** compared to a single AI.

## Why it's different

- **A debate, not a single voice.** Several models with different personalities and roles, taking turns.
- **On your machine, if you want.** Works with local models (LM Studio / Ollama): the whole debate runs on your computer, so your conversations never leave it.
- **You're in charge.** You moderate, step in, pause, and decide who speaks.

## Quick start

```bash
pip install -r requirements.txt
python -m uvicorn execution.api_server:app --port 8000
# open http://localhost:8000
```

To run it **100% on your machine** with your own models, see `docs/INSTALLATION.md` (local mode). Put your keys in `.env` (see `.env.example`); never commit real keys.

## Status

Young, evolving project. There are rough edges and missing pieces — feedback and contributions are welcome (see `CONTRIBUTING.md`).

## Contributing

We'd love your help. Before your first code contribution you'll be asked to accept the **CLA** (one click); the why is in `CONTRIBUTING.md`.

## License

H2AI Chat is released under **AGPL-3.0** (see `LICENSE`). You can use, study, modify, and share it freely. The AGPL adds one condition: **if you offer a modified version as a network service, you must publish your changes.** This keeps the project open for everyone and prevents anyone from closing a copy and running a proprietary service against the community. We also run a hosted version and an edition for companies at **h2aichat.com** (that's what funds development).

## Trademark

“H2AI Chat” and its logo are trademarks of **Miguel Ángel Suárez**. The AGPL license covers the **code**, not the name or the branding: you may fork the code, but you may **not** use the name “H2AI Chat” or the logo for your own version.
