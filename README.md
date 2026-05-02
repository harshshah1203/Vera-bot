# Vera Message Engine - One Signal, One Smart Move

This submission implements a deterministic message engine for magicpin's Vera challenge.

## Approach

The core artifact is:

```python
compose(category, merchant, trigger, customer=None) -> {
    "body": "...",
    "cta": "...",
    "send_as": "vera" | "merchant_on_behalf",
    "suppression_key": "...",
    "rationale": "..."
}
```

The product idea is **One Signal, One Smart Move**: every message names the concrete signal, gives a short merchant-growth diagnosis, recommends one ready-to-approve action, and ends with a simple CTA.

The implementation is deterministic and does not require an LLM API key. It uses trigger-specific builders for research, compliance, performance dips/spikes, competitor openings, review themes, renewals, winback, GBP verification, customer recall, customer refill, and trial follow-up flows.

## Why This Should Score Well

- Grounded: uses only category, merchant, trigger, and customer context fields.
- Useful: recommends a concrete action rather than generic growth advice.
- Category-fit: respects voice, taboos, offers, and vertical vocabulary.
- Merchant-aware: uses performance, offers, locality, owner names, signals, and conversation history.
- Reliable: deterministic, fast, and safe under judge timeouts.

## Running Locally

```bash
pip install -r requirements.txt
uvicorn bot:app --host 0.0.0.0 --port 8080
```

Health check:

```bash
curl http://localhost:8080/v1/healthz
```

## Deploying on Render

This repo is ready for Render and includes [render.yaml](</C:/Users/hksha/OneDrive/Documents/New project/render.yaml:1>) plus [Procfile](</C:/Users/hksha/OneDrive/Documents/New project/Procfile:1>).

1. Push this project to GitHub.
2. Go to [https://render.com](https://render.com) and create a new `Web Service`.
3. Connect the GitHub repo.
4. Render should detect:

```text
Build Command: pip install -r requirements.txt
Start Command: python -m uvicorn bot:app --host 0.0.0.0 --port $PORT
```

5. Deploy and wait for the public service URL.
6. Verify:

```bash
curl https://YOUR-RENDER-URL.onrender.com/v1/healthz
```

Submit the Render URL.

## Files That Matter

- [bot.py](</C:/Users/hksha/OneDrive/Documents/New project/bot.py:1>) contains the deterministic `compose()` engine and HTTP endpoints.
- [make_submission.py](</C:/Users/hksha/OneDrive/Documents/New project/make_submission.py:1>) regenerates [submission.jsonl](</C:/Users/hksha/OneDrive/Documents/New project/submission.jsonl:1>) from the same logic.
- [render.yaml](</C:/Users/hksha/OneDrive/Documents/New project/render.yaml:1>) and [Procfile](</C:/Users/hksha/OneDrive/Documents/New project/Procfile:1>) make deployment straightforward.

## Tradeoffs

I chose deterministic decision logic over LLM-generated copy to maximize repeatability, latency safety, and signal quality. The tradeoff is less linguistic variety, but the upside is consistent grounded behavior across fresh judge scenarios.

Additional context that would help most: exact merchant-approved campaign inventory, real availability slots, and city/locality peer benchmarks for each category.
