"""Sonde du cap gateway LiteLLM : durée vs tokens. Stdlib uniquement (aucun pip install).

    LITELLM_API_KEY=... python3 automation/tools/gateway_cap_probe.py vercel/anthropic-claude-sonnet-4.5
    LITELLM_API_KEY=... python3 automation/tools/gateway_cap_probe.py vercel/anthropic-claude-haiku-4.5

Interprétation :
- Les deux coupent à ~55k chars mais Haiku en ~2 min  -> cap de TOKENS côté gateway.
- Haiku va bien plus loin en chars, coupe vers ~5 min -> cap de DURÉE côté gateway.
- finish_reason: "length"=max_tokens, "stop"/None à ~55k = coupure gateway déguisée.
"""
import json
import os
import sys
import time
import urllib.request

BASE_URL = "https://llm-gateway.m33.tech"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "vercel/anthropic-claude-sonnet-4.5"

api_key = os.environ.get("LITELLM_API_KEY")
if not api_key:
    sys.exit("Définis LITELLM_API_KEY dans l'environnement.")

PROMPT = (
    "Écris une très longue encyclopédie numérotée de la réglementation des dispositifs "
    "médicaux en Europe. 500 sections. Chaque section: 5-6 phrases complètes. "
    "Ne t'arrête pas avant la section 500. Commence à la section 1."
)

body = json.dumps({
    "model": MODEL,
    "messages": [{"role": "user", "content": PROMPT}],
    "max_tokens": 60000,
    "stream": True,
}).encode("utf-8")

req = urllib.request.Request(
    f"{BASE_URL}/v1/chat/completions",
    data=body,
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    method="POST",
)

start = time.monotonic()
total = 0
finish_reason = None
last_log = start

print(f"modèle={MODEL} max_tokens=60000 demandé — go")
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = (choices[0].get("delta") or {}).get("content")
            if delta:
                total += len(delta)
            if choices[0].get("finish_reason"):
                finish_reason = choices[0]["finish_reason"]
            now = time.monotonic()
            if now - last_log > 10:
                print(f"  t={now - start:6.0f}s  chars={total:7d}  (~{total // 4} tokens)")
                last_log = now
except Exception as e:  # noqa: BLE001
    print(f"  EXCEPTION après {time.monotonic() - start:.0f}s / {total} chars : {type(e).__name__}: {e}")

elapsed = time.monotonic() - start
print(
    f"FIN — t={elapsed:.0f}s, chars={total} (~{total // 4} tokens), "
    f"finish_reason={finish_reason!r}"
)
