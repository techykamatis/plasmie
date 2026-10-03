# models/

Local model weights served to Claude Code and the pipeline via an MLX (Anthropic-compatible) endpoint on `127.0.0.1:8091`.

Each subdirectory is one MLX-converted Gemma-4 E-series model from
[mlx-community](https://huggingface.co/mlx-community), in the standard HF layout
(`config.json`, `*.safetensors`, `tokenizer.json`, chat template).

> **Not in git.** Weights are excluded by `models/.gitignore` (only this README
> and the `.gitignore` are tracked). A fresh clone has empty model dirs — download
> to populate them. Never `git add -f` the `.safetensors`; GitHub rejects files
> over 100 MB and these are gigabytes.

## Models

| Model | Where | Used by | Size | How it arrives |
|-------|-------|---------|------|----------------|
| Gemma-4 E4B, 4-bit (`mlx-community/gemma-4-e4b-it-4bit`) | `models/gemma-4-e4b/` | `mlx_serve.py` (port 8091) for `promote.sh`, the `summarize.sh` fallback, and `ask.py` answers | ~4.9 GB | `install.sh` step 6a or `app-setup.sh` (`hf download`, ungated, resumable); skipped if `config.json` already exists |
| qmd embedding + rerank models | qmd's own cache (not here) | retrieval: `ask.py` vector search, `qmd query`, the MCP server | ~3.7 GB (per `app-setup.sh`) | auto-downloaded by `qmd embed` (run by `app-setup.sh` and after every hourly ingest) |
| Apple Foundation Model | OS-managed | `fm.py`: `summarize.sh` first choice, tagging | none | needs macOS 26+ with Apple Intelligence on; not something this repo downloads |
| `mlx-community/embeddinggemma-300m-bf16` | HF cache | nothing at runtime | ~600 MB | `install.sh` step 6b still downloads it, but retrieval moved to qmd and no code imports `mlx_embeddings` now; the step is vestigial |

Only the Gemma weights live under `models/`.

## Download

The mlx-community reupload is **ungated** — anonymous download, no HF account:

```bash
hf download mlx-community/gemma-4-e4b-it-4bit --local-dir gemma-4-e4b
```

## Serve

`../mlx_serve.py` loads weights **non-strict** — the E-series conversion ships
redundant shared-KV tensors the model class doesn't define, which would abort a
strict load. Managed on-demand to keep RAM free when idle:

```bash
../mlx-ctl.sh up     # start, wait until model answers on :8091
../mlx-ctl.sh down   # stop, free RAM
../mlx-ctl.sh guard  # "ok" / "busy" — defer if the machine is hot or loaded
```

Point Claude Code at the endpoint with `../cc-local.sh`.

## Adding a model

1. `hf download <repo> --local-dir models/<name>`.
2. Add a row to the table above.
3. Nothing else to ignore — `.gitignore` already excludes everything but docs.
