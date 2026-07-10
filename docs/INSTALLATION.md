# Installation Guide

## Prerequisites

| Requirement | Version | Notes |
|:---|:---|:---|
| Python | 3.11+ | 3.13 in CI. Check with `python --version` |
| pip | 21.0+ | Included with Python 3.11+ |
| git | 2.30+ | To clone the repository |
| LM Studio or Ollama | latest | Optional, for running models locally |

> **In a hurry? One command with Docker.** If you have Docker, you can bring up the app **and** a local model server (Ollama) together, with nothing else to install: see [`RUN_LOCALLY.md`](RUN_LOCALLY.md). The manual, from-source steps below are the alternative.

---

## Step by step

### 1. Clone the repository

```bash
git clone https://github.com/Tonterias/h2aichat.git
cd h2aichat
```

### 2. Install dependencies

Work inside a **virtual environment** so you don't touch your global Python packages:

```bash
python -m venv .venv
source .venv/bin/activate              # Windows (PowerShell): .venv\Scripts\Activate.ps1

pip install -r requirements.txt        # runtime (just to start the server)
pip install -r requirements-dev.txt    # everything above + test/dev tools
```

Dependency **versions are pinned** in `requirements.txt` so everyone installs the same thing (reproducibility). SQLite is part of Python's standard library (no extra install needed).

### 3. Configure your API key

The cloud bots require an API key. There are two ways to provide it:

**Option A: environment variable**

```powershell
# PowerShell
$env:OPENCODE_API_KEY = "your-api-key"
```

```bash
# Linux / macOS
export OPENCODE_API_KEY="your-api-key"
```

**Option B: an `auth.json` file**

Create `~/.local/share/opencode/auth.json` — on **Windows** the same path lives under your user folder: `%USERPROFILE%\.local\share\opencode\auth.json`:

```json
{
  "opencode-go": { "key": "your-api-key" }
}
```

The client looks first at `auth.json`, then at the `OPENCODE_API_KEY` environment variable.

**OpenRouter (optional):** to use models via [OpenRouter](https://openrouter.ai) (OpenAI, Anthropic, Google, and hundreds more), add the key to `auth.json`:

```json
{
  "openrouter": { "type": "api", "key": "sk-or-v1-your-openrouter-key" }
}
```

Or as an environment variable (`OPENROUTER_API_KEY`).

> **Tip:** prefer local models (next section) if you want to run everything on your own machine with no data leaving it.

### 4. Start the server

```bash
python -m uvicorn execution.api_server:app --port 8000
```

The server starts at `http://localhost:8000`. Open that URL in your browser.

### 5. Verify

```bash
curl http://localhost:8000/status
```

You should get a small JSON with the engine state (`"state": "idle"`, empty queue and participants).

---

## Running with local models (private mode)

To run the whole debate on your own machine, with **no data leaving it**:

1. Install [LM Studio](https://lmstudio.ai/) (local server on `localhost:1234`) or [Ollama](https://ollama.com/) (`localhost:11434`).
2. Load a model (for example a Qwen, Llama, or Mistral model).
3. Start the local server and check it responds:
   ```bash
   curl http://localhost:1234/v1/models      # LM Studio
   ```
4. Point an agent's provider to your local server in the AI catalog (editable from the admin panel).

> **Privacy note:** on our side, nothing leaves your machine. Still, make sure you use a **trusted model** — prefer weights-only formats and don't enable "trust remote code" from unknown authors.

> **Performance note:** a model on your own machine runs as fast as your hardware. On a normal laptop it will be slower than the cloud; for several agents debating, a machine with a good GPU helps.

---

## Run the tests

```bash
python -m unittest discover -s execution/tests -v
```

The tests are plain `unittest`, so no extra runner is required. (Our CI runs the same suite with `pytest` — either works.)

---

## Troubleshooting

See `docs/TROUBLESHOOTING_AND_FAQ.md` for common issues. A few quick ones:

- **Frontend won't load** → the server isn't running; start it (step 4).
- **Bots don't respond** → check your API key (`auth.json` or `OPENCODE_API_KEY`), or that your local model server is up.
- **Port 8000 in use** → start on another port: `--port 8001`.
