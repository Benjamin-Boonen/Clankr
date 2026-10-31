# Homepage resilience when Ollama model metadata fails

## Symptom
The homepage can return HTTP 500 while building the model picker. `get_models()` lists installed tags, then calls `/api/show` for each model to discover capabilities. If Ollama returns an error for one model (for example, GGUF metadata parsing fails with `unsupported tensor "output.weight" size overflows`), that exception previously aborted the entire request.

## Change
`get_models()` now catches a capability lookup failure per model, logs the failure, and still returns that installed model with an empty capability list. Other models can still be listed and selected. The error is exposed in the returned model data as `caps_error` for future UI display, but it does not mark the model as healthy; attempting to run it may still fail until the underlying Ollama/model issue is resolved.

## Underlying Ollama error
This patch prevents a single broken model from taking down the Pyggie homepage. It does not repair the model blob or GGUF metadata. The exact root cause should be investigated on the Ollama host: identify which model triggers the error, inspect the Ollama server logs and version, and determine whether the local model data is incomplete/incompatible or whether an Ollama update is needed. Avoid deleting model blobs manually because they may be shared by multiple tags.

## Validation
Run from `pyggie/`:

```bash
python manage.py check
python manage.py test home
```

A regression test mocks an Ollama capability lookup failure and verifies that `get_models()` still returns the model. These commands have not been run by the remote editing session.
