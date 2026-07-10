# Run it 100% on your machine

You can run the whole multi-AI debate **on your own computer, with your own models**, so **your conversations never leave your machine**. This is the thing hosted alternatives can't offer.

There are two ways: the easy all-in-one (Docker), or manual (LM Studio / Ollama).

---

## Option A — All-in-one with Docker (easiest)

This brings up H2AI Chat **and** a local model server (Ollama), already wired together.

```bash
docker compose up -d                              # start the app + Ollama
docker compose exec ollama ollama pull llama3.2   # download a model (once)
# open http://localhost:8000
```

It comes **ready to debate**: a local-mode instance ships with an agent called **"Local"** already set to your Ollama (`llama3.2`), so you can just type a question and go. No login is needed on a local instance.

Want more control? In **`/admin` → "Configuración de la aplicación"** the local server is already pointed at Ollama — add or edit agents (set provider to **local** and pick any model you pulled) and use **"Probar conexión"** to check it responds.

That's it — the debate runs entirely inside your machine.

---

## Option B — Manual (LM Studio or Ollama)

1. Install **[LM Studio](https://lmstudio.ai/)** (local server on `localhost:1234`) or **[Ollama](https://ollama.com/)** (`localhost:11434`).
2. Load / pull a model (a Llama, Qwen, or Mistral, for example).
3. Start the local server.
4. In **`/admin`**, set the **local server address** with the preset button (LM Studio or Ollama), and press **"Probar conexión"** — it should say *Connected* and list your models.
5. Set an agent's provider to **local** and pick the model.

---

## Privacy — the honest version

- **On our side, nothing leaves your machine.** H2AI Chat does not send your conversations anywhere when your agents use local models. We control and guarantee that.
- **But make sure you use a trusted model.** Our app not sending anything does **not** by itself guarantee that the *model* you downloaded won't. To be safe with confidential data:
  - Prefer **weights-only formats** (GGUF, safetensors) — they're data, not a program, so they can't "call home".
  - **Don't enable "trust remote code"** from unknown authors.
  - Download models from **recognized sources** (official Meta / Qwen / Mistral repos, or well-known mirrors).
  - Remember the **model runner itself** (Ollama / LM Studio) is third-party software; use official builds.
- With cloud models using **your own API keys**, the text goes to that provider (OpenAI, etc.) but **never to us**.

## Performance note

A model on your own machine runs **as fast as your hardware**. On a normal laptop it will be slower than the cloud; for several agents debating, a machine with a **good GPU** helps a lot.
