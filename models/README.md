# models/

Local model weights served to Claude Code via an MLX (Anthropic-compatible) endpoint.

Each subdirectory is one MLX-converted Gemma-4 E-series model from
[mlx-community](https://huggingface.co/mlx-community), in the standard HF layout
(`config.json`, `*.safetensors`, `tokenizer.json`, chat template).

> **Not in git.** Weights are excluded by `models/.gitignore` (only this README
> and the `.gitignore` are tracked). A fresh clone has empty model dirs — download
> to populate them. Never `git add -f` the `.safetensors`; GitHub rejects files
> over 100 MB and these are gigabytes.

## Models

| Dir | Source repo | Quant | On-disk |
|-----|-------------|-------|---------|
| `gemma-4-e4b/` | `mlx-community/gemma-4-e4b-it-4bit` | 4-bit | ~4.9 GB |

## Download

Weights are gated — needs a Hugging Face token (`huggingface-cli login`):

```bash
huggingface-cli download mlx-community/gemma-4-e4b-it-4bit --local-dir gemma-4-e4b
```

## Serve

`../mlx_serve.py` loads weights **non-strict** — the E-series conversion ships
redundant shared-KV tensors the model class doesn't define, which would abort a
strict load. Managed on-demand to keep RAM free when idle:

```bash
../mlx-ctl.sh up     # start, wait until model answers on :8080
../mlx-ctl.sh down   # stop, free RAM
../mlx-ctl.sh guard  # "ok" / "busy" — defer if the machine is hot or loaded
```

Point Claude Code at the endpoint with `../cc-local.sh`.

## Adding a model

1. `huggingface-cli download <repo> --local-dir models/<name>`.
2. Add a row to the table above.
3. Nothing else to ignore — `.gitignore` already excludes everything but docs.
