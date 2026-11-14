# AIRLLM backend (experimental)

AIRLLM is an optional second inference backend. Ollama remains the default and
continues to power Agent Mode, tool calling, vision descriptions and ordinary
chat. This first integration exposes AIRLLM for **text-only direct chat**; it
does not yet support Agent Mode, native tool calls or vision.

## Architecture

- Django/Pyggie talks to a small HTTP sidecar on `127.0.0.1:8091`.
- The sidecar loads one Hugging Face model at startup and streams generated
  text as newline-delimited JSON.
- The sidecar runs separately so its PyTorch/AIRLLM dependencies cannot break
  the existing Django/Ollama environment.
- The model picker shows the configured model as `AIRLLM · …` when
  `CLANKR_AIRLLM_MODEL` is set.

## Installation

Use a dedicated virtual environment. Do not install AIRLLM's dependencies into
Pyggie's existing environment.

```bash
cd ~/Documents/Clankr/pyggie
python3 -m venv .venv-airllm
source .venv-airllm/bin/activate
python -m pip install --upgrade pip
# First install a PyTorch build compatible with your NVIDIA GPU and driver.
# Then install the optional sidecar dependencies:
python -m pip install -r requirements-airllm.txt
```

Pascal GPUs such as the GTX 1070 require a PyTorch/CUDA build that still
contains Pascal kernels. A driver advertising a recent CUDA version does not
guarantee that the matching newest PyTorch wheel supports this GPU. Verify
`torch.cuda.is_available()` and `torch.cuda.get_device_name(0)` inside this
environment before downloading a large model.

## Configure and run

Use the same Hugging Face model ID in both processes. Start with a small model
to validate the environment before trying a larger one.

```bash
# Terminal 1 — sidecar
cd ~/Documents/Clankr/pyggie
source .venv-airllm/bin/activate
export AIRLLM_MODEL="Qwen/Qwen3-8B"
export AIRLLM_COMPRESSION="4bit"   # optional: 4bit, 8bit, or unset
uvicorn airllm_server:app --host 127.0.0.1 --port 8091
```

In the environment used by Django:

```bash
export CLANKR_AIRLLM_MODEL="Qwen/Qwen3-8B"
export CLANKR_AIRLLM_URL="http://127.0.0.1:8091"
```

Restart Django after changing these settings. The AIRLLM model appears beside
Ollama models in the picker. The first model preparation can require substantial
extra disk space and can take a long time; monitor free space before starting.

## Operational notes

- Only one AIRLLM model is loaded by the sidecar at a time.
- Keep the sidecar bound to loopback. It has no authentication and is not
  intended to be exposed to a LAN or the public internet.
- Ollama and AIRLLM can coexist, but both compete for GPU memory, system RAM,
  CPU and disk bandwidth. On a small machine, avoid simultaneous generations.
- AIRLLM requests are not routed through Ollama. Chat history is retained by
  Pyggie, but AIRLLM currently receives only system/user/assistant text.
- Agent Mode is Ollama-only until AIRLLM has a compatible tool-call adapter.
- The sidecar does not cancel a running model generation when the browser
  disconnects; it lets the worker finish to avoid leaving model state unsafe.

## Troubleshooting

- `/health` reports `error`: inspect the sidecar traceback; check the model ID,
  Hugging Face access, free disk space and the installed PyTorch build.
- `Can't reach the AIRLLM sidecar`: confirm Uvicorn is running on port 8091 and
  `CLANKR_AIRLLM_URL` matches.
- CUDA is unavailable: verify the PyTorch/CUDA combination in the sidecar
  environment before downloading model weights.
- Very slow generation: AIRLLM streams layers from disk; a SATA SSD and older
  CPU can make it much slower than a model already resident in Ollama.
