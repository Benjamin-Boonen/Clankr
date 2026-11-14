"""Optional AIRLLM inference sidecar for Clankr.

Run from the pyggie directory in a dedicated AIRLLM-compatible environment:
    AIRLLM_MODEL=Qwen/Qwen3-14B uvicorn airllm_server:app --host 127.0.0.1 --port 8091

The model is loaded once at startup. Only one model is served by this first
integration; it does not expose arbitrary model paths or remote code execution.
"""
import json
import os
import queue
import threading
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

MODEL_ID = os.environ.get("AIRLLM_MODEL", "").strip()
COMPRESSION = os.environ.get("AIRLLM_COMPRESSION", "").strip().lower()
MAX_INPUT_TOKENS = int(os.environ.get("AIRLLM_MAX_INPUT_TOKENS", "8192"))
DEFAULT_MAX_NEW = int(os.environ.get("AIRLLM_MAX_NEW_TOKENS", "1024"))

app = FastAPI(title="Clankr AIRLLM sidecar", docs_url=None, redoc_url=None)
model = None
tokenizer = None
load_error = None


class GenerateRequest(BaseModel):
    model: str
    messages: list[dict] = Field(default_factory=list)
    max_new_tokens: int = Field(default=DEFAULT_MAX_NEW, ge=1, le=4096)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


@app.on_event("startup")
def load_model():
    global model, tokenizer, load_error
    if not MODEL_ID:
        load_error = "AIRLLM_MODEL is not set."
        return
    try:
        from airllm import AutoModel
        kwargs = {}
        if COMPRESSION in ("4bit", "8bit"):
            kwargs["compression"] = COMPRESSION
        model = AutoModel.from_pretrained(MODEL_ID, **kwargs)
        tokenizer = model.tokenizer
    except Exception as exc:
        load_error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()


@app.get("/health")
def health():
    return {
        "status": "ready" if model is not None else "error" if load_error else "loading",
        "model": MODEL_ID,
        "error": load_error,
    }


def _prompt(messages):
    clean = []
    for item in messages:
        role = item.get("role")
        if role not in ("system", "user", "assistant"):
            continue
        content = item.get("content")
        if isinstance(content, str) and content:
            clean.append({"role": role, "content": content})
    if hasattr(tokenizer, "apply_chat_template"):
        try:
            return tokenizer.apply_chat_template(
                clean, tokenize=False, add_generation_prompt=True
            )
        except (TypeError, ValueError, AttributeError):
            pass
    return "\n".join(
        f"{item['role'].upper()}: {item['content']}" for item in clean
    ) + "\nASSISTANT:"


def _ndjson(request):
    import torch
    from transformers import TextIteratorStreamer

    prompt = _prompt(request.messages)
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=MAX_INPUT_TOKENS,
        return_attention_mask=True,
    )
    device = getattr(model, "device", "cuda:0" if torch.cuda.is_available() else "cpu")
    input_ids = inputs["input_ids"].to(device)
    attention_mask = inputs.get("attention_mask")
    if attention_mask is not None:
        attention_mask = attention_mask.to(device)

    streamer = TextIteratorStreamer(
        tokenizer, skip_prompt=True, skip_special_tokens=True, timeout=None
    )
    errors = queue.Queue()

    def generate():
        try:
            kwargs = {
                "input_ids": input_ids,
                "max_new_tokens": min(request.max_new_tokens, 4096),
                "use_cache": True,
                "return_dict_in_generate": True,
                "streamer": streamer,
            }
            if attention_mask is not None:
                kwargs["attention_mask"] = attention_mask
            if request.temperature > 0:
                kwargs.update(do_sample=True, temperature=request.temperature)
            else:
                kwargs["do_sample"] = False
            with torch.inference_mode():
                model.generate(**kwargs)
        except Exception as exc:
            errors.put(f"{type(exc).__name__}: {exc}")
        finally:
            streamer.end()

    worker = threading.Thread(target=generate, daemon=True)
    worker.start()
    try:
        for token in streamer:
            if token:
                yield json.dumps({"token": token}, ensure_ascii=False) + "\n"
        worker.join()
        if not errors.empty():
            yield json.dumps({"error": errors.get()}, ensure_ascii=False) + "\n"
        else:
            yield '{"done":true}\n'
    except GeneratorExit:
        # A disconnected client cannot safely cancel an in-flight generate call.
        # Let the worker finish rather than corrupting AIRLLM's layer state.
        worker.join()


@app.post("/generate")
def generate(request: GenerateRequest):
    if model is None:
        detail = load_error or "AIRLLM model is still loading."
        raise HTTPException(status_code=503, detail=detail)
    if request.model != MODEL_ID:
        raise HTTPException(status_code=400, detail="Requested model does not match AIRLLM_MODEL.")
    if not request.messages:
        raise HTTPException(status_code=400, detail="At least one message is required.")
    return StreamingResponse(_ndjson(request), media_type="application/x-ndjson")
