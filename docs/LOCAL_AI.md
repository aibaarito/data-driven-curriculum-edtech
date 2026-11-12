# Local AI explanations with Qwen3-8B and Ollama

The **ИИ-пояснения** page can use a language model to put verified results into plain Russian. This guide sets
that up with **Qwen3-8B running locally through [Ollama](https://ollama.com)**, so explanations work without a
Gemini key or any internet connection after installation.

This is a local integration of a pretrained, post-trained open-weight model published by the Qwen team. We did not
train or fine-tune it. The model only rewords facts that the backend has already calculated; mastery, statistical
significance, textbook verdicts and hour allocations are computed by deterministic code and are never decided by
the model.

## How it works

1. The backend calculates the analysis for the selected filters and builds a list of aggregate facts
   (`topic.T7-05.mastery`, `comparison.0.verdict`, …). No student identifiers, raw rows or credentials are sent.
2. It calls Ollama's native chat endpoint `POST http://127.0.0.1:11434/api/chat` with:
   * `"think": false`: Qwen3's reasoning mode is switched off through Ollama's documented control, not just by
     asking in the prompt. Any `thinking` field in the reply is ignored, and a leftover `<think>` tag rejects the
     answer.
   * `"format"`: the JSON Schema generated from the backend's own Pydantic model `LLMPayload`. Ollama
     constrains generation to that structure, and the backend validates the result with the same model.
   * Sampling options from the Qwen3 model card for non-thinking mode: `temperature 0.7`, `top_p 0.8`,
     `top_k 20`, `min_p 0`. Also `num_ctx` (context) and `num_predict` (output limit).
3. The model may write numbers and names only as placeholders such as `{{mastery}}` or `{{name}}`. The backend
   fills them in from the facts and then checks every number against the facts for that topic or comparison. It
   also rejects causal claims, contradictions of the computed status or trend, a "better textbook" when evidence
   is insufficient, and internal codes such as `difficult` left in the Russian text.
4. If the answer is rejected, the model gets **one** retry with the same facts plus the rule it broke. If that
   also fails, or the service is down, the page shows the deterministic template explanations and says why.

The native API is used instead of Ollama's OpenAI-compatible `/v1` endpoint because it reports `done_reason`
(so an answer cut off by the output limit is detected) and returns a clear 404 when the model is not installed.
Both endpoints document thinking and schema controls; the native one gives the backend both signals it needs.

## 1. Install Ollama (official source)

* **macOS:** download the app from <https://ollama.com/download>, or `brew install ollama`.
* **Linux:** `curl -fsSL https://ollama.com/install.sh | sh` (read the script first), or download the release
  archive from the same page.

Check the version:

```bash
ollama --version
```

The integration was verified with **Ollama 0.40.16**.

## 2. Run Ollama locally only

Ollama listens on `127.0.0.1:11434` by default. Keep it that way: do not set `OLLAMA_HOST=0.0.0.0` and do not
create tunnels. Also turn off Ollama's cloud features so a cloud model can never be used by accident. Do this
**on the Ollama server**: adding the setting to the application's `backend/.env` has no effect on Ollama.

Either add this to `~/.ollama/server.json`:

```json
{ "disable_ollama_cloud": true }
```

or start the server with the environment variable:

```bash
OLLAMA_NO_CLOUD=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 ollama serve
```

If the macOS menu-bar app is running, quit it first, or set the variables with
`launchctl setenv OLLAMA_NO_CLOUD 1` and restart the app. After a restart, the Ollama log should contain
`Ollama cloud disabled: true`.

## 3. Download the model

```bash
ollama pull qwen3:8b
ollama show qwen3:8b      # expect: qwen3 · 8.2B · Q4_K_M · thinking
```

`qwen3:8b` is Qwen3 8B in GGUF format, 4-bit **Q4_K_M** quantization, about **5.2 GB** to download.
Runtime memory is larger than the download: the weights plus the context cache and buffers. The live evaluation
records the peak memory of the Ollama processes; see [VERIFICATION.md](VERIFICATION.md). On a 16 GB Mac, close
other large apps during a demo.

## 4. Configure the application

Edit only the private file `backend/.env`. Comment out the old provider lines rather than deleting them, so a
saved Gemini key stays where it was and is never printed:

```dotenv
# LLM_PROVIDER=openai_compatible   # previous Gemini settings, kept for later
# LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
# LLM_MODEL=gemini-3.8-flash
LLM_PROVIDER=ollama
LLM_BASE_URL=http://127.0.0.1:11434
LLM_MODEL=qwen3:8b
LLM_TIMEOUT_SECONDS=120
LLM_TOTAL_TIMEOUT_SECONDS=240
```

* The `ollama` provider needs **no API key** and sends no `Authorization` header. If `LLM_API_KEY` is still set
  for Gemini, it is ignored while `LLM_PROVIDER=ollama`. If another tool insists on a key for Ollama's `/v1`
  endpoint, the conventional placeholder is `ollama`. It is not a secret and does not protect the server.
* `LLM_BASE_URL` may also be written as `http://127.0.0.1:11434/v1`; the backend uses the native API at the root.
* These settings are read by the backend only. `./dev.sh` strips every `LLM_*` variable from the frontend
  process, and nothing is exposed through `NEXT_PUBLIC_*` variables.

Optional limits (defaults shown):

| Variable | Default | Meaning |
|---|---|---|
| `LLM_TIMEOUT_SECONDS` | 30 | Per model call. Use about 120 for a local 8B model; the first call also loads the weights |
| `LLM_TOTAL_TIMEOUT_SECONDS` | 2 × per-call, at most 280 | Both attempts together; a retry is not started after the deadline. Capped at 280 s because the Next.js proxy stops waiting for the backend after 300 s |
| `LLM_MAX_CONCURRENCY` | 1 | Model calls at once per backend process; another request gets templates immediately |
| `LLM_MAX_OUTPUT_TOKENS` | 2048 | Ollama `num_predict`; an answer cut off at this limit is rejected |
| `LLM_CONTEXT_TOKENS` | 12288 | Ollama `num_ctx`. The grade-7 demo prompt measured 4,479 tokens; all grades about 14,400 characters. A prompt that might not fit with the output (estimated at 2 characters per token) uses templates, because Ollama would otherwise silently drop part of it |
| `LLM_MAX_INPUT_CHARS` | 24000 | Larger fact sets use templates. Facts are never silently truncated |
| `LLM_KEEP_ALIVE` | 10m | How long Ollama keeps the model loaded after a request |

## 5. Restart the backend

Restart only the backend of the checkout you are using, so it reads the new `backend/.env`. With the helper:

```bash
./dev.sh stop
./dev.sh start
```

or, for a manual start, stop that `uvicorn` process with `Ctrl+C` and start it again
(`uvicorn app.main:app --host 127.0.0.1 --port 8010`). Several old checkouts may have run on port 3010. Before
restarting anything, check which folder a process belongs to, for example `lsof -nP -iTCP:8010 -sTCP:LISTEN`
followed by `lsof -p <PID> | grep cwd`.

Then open <http://127.0.0.1:3010/insights>, choose filters and press **Сформировать пояснения**. A successful
answer is labelled **«Пояснения написала локальная модель qwen3:8b (Ollama, на этом компьютере)»**. Template
explanations are always labelled as templates and give the reason.

![The AI explanations page for Mathematics, grade 8, on synthetic data. The banner reads 'Пояснения написала локальная модель qwen3:8b (Ollama, на этом компьютере)' with 'Числа сверены с расчётами'; below it a summary and two findings about topics with a statistically significant increase, each with the backend facts it relies on.](assets/local-ai-qwen.png)

*An accepted Qwen3-8B answer in the application (synthetic data, grade 8), recorded during verification.*

## 6. Tests

Automated tests mock Ollama and need no model, network or API key:

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://USER@127.0.0.1:5432/ddc_verify_test python -m pytest -q tests/test_ai_ollama.py tests/test_ai.py
```

The live evaluation is separate and opt-in. It uses 22 synthetic aggregate contexts, never the application
database, and refuses any non-loopback endpoint:

```bash
cd backend
python scripts/eval_local_llm.py --live --timeout 180 --out /tmp/local-llm-eval.json
```

Without `--live` it makes no calls. The JSON summary lists the model, quantization, Ollama version, settings,
first-attempt and retry acceptance, rejection categories, cold and warm latency, and peak memory.

## 7. What the page tells you

| Banner | Meaning | What to do |
|---|---|---|
| Пояснения написала локальная модель qwen3:8b | Accepted model answer | — |
| Локальная модель недоступна | Nothing answers on the Ollama port | Start Ollama (`ollama serve` or the app) |
| Модель не установлена | Ollama runs but `qwen3:8b` is missing | `ollama pull qwen3:8b` |
| Модель не ответила вовремя | Per-call or total timeout reached | Retry once the model is loaded, or raise `LLM_TIMEOUT_SECONDS` |
| Ответ модели отклонён | Both answers failed validation | Normal occasionally; templates are correct. Check the backend log for the rule category |
| Модель занята | Another explanation is being generated | Wait and retry |
| Слишком много фактов для модели | The fact set exceeds `LLM_MAX_INPUT_CHARS` | Narrow the filters or raise the limit together with `LLM_CONTEXT_TOKENS` |

## 8. Switching providers

* **Templates only:** set `LLM_PROVIDER=none` and restart the backend.
* **Back to a remote provider:** uncomment your previous `LLM_PROVIDER`, `LLM_BASE_URL` and `LLM_MODEL` lines and
  comment out the Ollama lines. The key you saved earlier is used again; it is never shown by the app.

## Limits of this setup

* **Local only.** A backend deployed to Railway or any other host cannot reach Ollama on your Mac. This guide does
  not create a public deployment.
* **Validation is heuristic beyond numbers.** Number and entity binding is enforced structurally. Wording checks
  are pattern lists, so a reader should still review explanations before sharing them.
* **Speed depends on the machine.** See [VERIFICATION.md](VERIFICATION.md) for the measured results and the
  hardware they were measured on.
* **Measured quality is not demo-ready.** In the live evaluation (22 synthetic contexts, Linux CPU), 6 answers
  were accepted and 16 contexts fell back to templates; every rejection was a real rule violation. Of the 6
  accepted answers, 2 were fully sound on manual review; the others contained a mislabelled value, an invented
  hours recommendation or a false comparison ("60 учеников не достигает порога 10"). Treat model text as a draft
  for a person to check. The template explanations remain the reliable default.
