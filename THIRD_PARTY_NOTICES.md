# Third-party notices

Plasmie is licensed under the GNU General Public License, version 3 or later (see
[LICENSE](LICENSE)). It ships, installs or downloads the third-party components below, each
under its own license. Every bundled component keeps its own license file inside the app, at
the path given for it; this file is a guide to them and lives in the app as
`Plasmie.app/Contents/Resources/THIRD_PARTY_NOTICES.md`, next to Plasmie's own `LICENSE`.

Apple's frameworks (SwiftUI, AppKit, FoundationModels) and the on-device model behind
Apple Intelligence come with macOS. Plasmie links against them but does not ship them.

- [Bundled in Plasmie.app](#bundled-in-plasmieapp)
  - [Python (CPython 3.12.11, python-build-standalone build)](#python-cpython-31211-python-build-standalone-build)
  - [pip 24.3.1](#pip-2431)
  - [Node.js v22.23.3](#nodejs-v22233)
- [Installed at setup: qmd](#installed-at-setup-qmd)
- [Downloaded at setup: the search models](#downloaded-at-setup-the-search-models)

---

## Bundled in Plasmie.app

### Python (CPython 3.12.11, python-build-standalone build)

- **Version:** CPython 3.12.11, python-build-standalone release `20250612`
  (`cpython-3.12.11+20250612-<arch>-apple-darwin-install_only.tar.gz`), pinned in
  `app/make-app.sh` (`PYVER`, `PYTAG`)
- **Homepage:** https://www.python.org/ and https://github.com/astral-sh/python-build-standalone
- **License:** Python Software Foundation License (SPDX `Python-2.0`, with the CNRI, BeOpen
  and CWI licenses it includes). The bundled libraries listed below have their own licenses.
- **In the app:** `Contents/Resources/python/` (setup copies it to Plasmie's own folder).

CPython's license is long and covers several historical licenses plus code CPython itself
includes, so it is shipped verbatim instead of being copied here:

- `Contents/Resources/python/lib/python3.12/LICENSE.txt` is CPython's license, from the
  release tarball.
- `Contents/Resources/python/licenses/LICENSE.cpython.txt` is the same license plus the
  licenses of third-party code in CPython's source tree, as python-build-standalone ships it.

The libraries this Python build links are licensed separately. The install-only tarball that
Plasmie bundles does not include their licenses, so they come verbatim from the same
release's full archive (`cpython-3.12.11+20250612-aarch64-apple-darwin-pgo+lto-full.tar.zst`,
`python/licenses/`, SHA-256 checked against the release). They are kept in the repository at
`app/licenses/python/` and shipped in `Contents/Resources/python/licenses/`:

| Library | Version | License | File in `python/licenses/` |
|---|---|---|---|
| OpenSSL | 3.0.16 | Apache-2.0 | `LICENSE.openssl-3.txt` (`LICENSE.openssl-1.1.txt` also shipped) |
| SQLite | 3.47.1 | Public domain | `LICENSE.sqlite.txt` |
| Expat | 2.6.3 | MIT | `LICENSE.expat.txt` |
| mpdecimal | 4.0.0 | BSD-2-Clause | `LICENSE.mpdecimal.txt` |
| Tcl/Tk | 8.6.14 | Tcl/Tk license (TCL) | `LICENSE.tcl.txt` |
| libffi | as built by python-build-standalone 20250612 | MIT | `LICENSE.libffi.txt` |
| bzip2 | as built by python-build-standalone 20250612 | bzip2-1.0.6 | `LICENSE.bzip2.txt` |
| liblzma (XZ Utils) | as built by python-build-standalone 20250612 | Public domain | `LICENSE.liblzma.txt` |
| libedit | as built by python-build-standalone 20250612 | BSD-3-Clause | `LICENSE.libedit.txt` |
| ncurses | as built by python-build-standalone 20250612 | X11 (MIT-style) | `LICENSE.ncurses.txt` |
| libuuid | as built by python-build-standalone 20250612 | BSD-3-Clause | `LICENSE.libuuid.txt` |
| zlib | as reported by the runtime: 1.2.12 | Zlib | `LICENSE.zlib.txt` |

The folder also holds, as shipped by python-build-standalone for all of its platforms,
`LICENSE.bdb.txt`, `LICENSE.libX11.txt`, `LICENSE.libXau.txt`, `LICENSE.libxcb.txt` and
`LICENSE.tix.txt`, and the license of python-build-standalone's own build tooling (Mozilla
Public License 2.0, from the project's repository at tag `20250612`) as
`LICENSE.python-build-standalone.txt`.

The CPython distribution also contains `lib/python3.12/ensurepip/_bundled/pip-25.0.1-py3-none-any.whl`,
an unused wheel archive that carries its own license inside it.

### pip 24.3.1

- **Version:** 24.3.1, as included in the python-build-standalone build above
- **Homepage:** https://pip.pypa.io/
- **License:** MIT
- **In the app:** `Contents/Resources/python/lib/python3.12/site-packages/pip/`, with its
  license in `site-packages/pip-24.3.1.dist-info/LICENSE.txt`

```
Copyright (c) 2008-present The pip developers (see AUTHORS.txt file)

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

pip bundles ("vendors") the packages below. pip's wheel does not include their license
files, so they come verbatim from pip's source repository at tag `24.3.1`
(`src/pip/_vendor/`). They are kept at `app/licenses/pip-24.3.1/_vendor/` and shipped in
`Contents/Resources/python/licenses/pip-24.3.1/_vendor/`:

| Package | Version | License | File in `_vendor/` |
|---|---|---|---|
| cachecontrol | 0.14.0 | Apache-2.0 | `cachecontrol/LICENSE.txt` |
| certifi | 2024.8.30 | MPL-2.0 | `certifi/LICENSE` |
| distlib | 0.3.9 | PSF-2.0 | `distlib/LICENSE.txt` |
| distro | 1.9.0 | Apache-2.0 | `distro/LICENSE` |
| idna | 3.7 | BSD-3-Clause | `idna/LICENSE.md` |
| msgpack | 1.0.8 | Apache-2.0 | `msgpack/COPYING` |
| packaging | 24.1 | Apache-2.0 OR BSD-2-Clause | `packaging/LICENSE`, `LICENSE.APACHE`, `LICENSE.BSD` |
| pkg_resources | from setuptools 70.3.0 | MIT | `pkg_resources/LICENSE` |
| platformdirs | 4.2.2 | MIT | `platformdirs/LICENSE` |
| pygments | 2.18.0 | BSD-2-Clause | `pygments/LICENSE` |
| pyproject_hooks | 1.0.0 | MIT | `pyproject_hooks/LICENSE` |
| requests | 2.32.3 | Apache-2.0 | `requests/LICENSE` |
| resolvelib | 1.0.1 | ISC | `resolvelib/LICENSE` |
| rich | 13.7.1 | MIT | `rich/LICENSE` |
| tomli | 2.0.1 | MIT | `tomli/LICENSE` |
| truststore | 0.10.0 | MIT | `truststore/LICENSE` |
| typing_extensions | 4.12.2 | PSF-2.0 | `typing_extensions.LICENSE` |
| urllib3 | 1.26.20 | MIT | `urllib3/LICENSE.txt` |

### Node.js v22.23.3

- **Version:** v22.23.3 (`node-v22.23.3-darwin-<arch>.tar.gz` from nodejs.org, checked
  against its `SHASUMS256.txt`), pinned in `app/make-app.sh` (`NODEVER`)
- **Homepage:** https://nodejs.org/
- **License:** MIT, plus the licenses of the many dependencies built into Node.js (V8, ICU,
  OpenSSL, libuv, llhttp, zlib, undici, npm and others)
- **In the app:** `Contents/Resources/node/`, with the full license at
  `Contents/Resources/node/LICENSE`

Node.js's `LICENSE` file is about 145 KB, with a section for each bundled dependency, so it
is shipped verbatim in the app rather than copied here. Its opening section, quoted from the
file, reads:

```
Node.js is licensed for use as follows:

"""
Copyright Node.js contributors. All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to
deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE.
"""
```

Two packages ship inside the Node.js distribution with their own license files:

| Package | Version | License | In the app |
|---|---|---|---|
| npm | 10.9.9 | Artistic-2.0 | `Contents/Resources/node/lib/node_modules/npm/LICENSE` |
| corepack | 0.36.0 | MIT | `Contents/Resources/node/lib/node_modules/corepack/LICENSE.md` |

---

## Installed at setup: qmd

Plasmie does not ship qmd. During setup the bundled Node installs it from the npm registry
into Plasmie's own folder (`~/Library/Application Support/Plasmie/qmd`). npm downloads qmd
and its dependencies straight from the registry, and each package keeps its own license file
in that folder.

- **Package:** [`@tobilu/qmd`](https://www.npmjs.com/package/@tobilu/qmd)
- **Version:** 2.5.3, pinned in `app-setup.sh` (`QMD_VERSION`)
- **Homepage:** https://github.com/tobi/qmd
- **License:** MIT (from the package's `package.json` and `LICENSE`, which match the
  upstream repository at tag `v2.5.3`)

```
MIT License

Copyright (c) 2024-2026 Tobi Lutke

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

qmd 2.5.3's dependency tree has 253 npm packages: 214 MIT, 23 ISC, 5 BlueOak-1.0.0,
3 Apache-2.0, 3 BSD-3-Clause, 1 BSD-2-Clause, and a few dual-licensed packages
(sqlite-vec: MIT or Apache-2.0; rc: BSD-2-Clause, MIT or Apache-2.0; expand-template: MIT or
WTFPL). Among them are node-llama-cpp (MIT), which runs the search models with a prebuilt
llama.cpp (MIT), better-sqlite3 (MIT) and sqlite-vec. Each license is in that package's folder
under `~/Library/Application Support/Plasmie/qmd/lib/node_modules/`.

---

## Downloaded at setup: the search models

Plasmie does not ship or redistribute these models. qmd downloads them directly from
Hugging Face into its model cache (`~/.cache/qmd/models`) the first time it needs each one:
setup's indexing step fetches the embedding model, the first search fetches the
query-expansion model, and the reranker is fetched only if qmd's hybrid `query` command is
used. Your use of each model is governed by its own license or terms, below. The licenses
were checked against each model's Hugging Face model card on 2026-10-20.

| Model (as qmd 2.5.3 names it) | Used for | Based on | License / terms |
|---|---|---|---|
| [`ggml-org/embeddinggemma-300M-GGUF`](https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF), file `embeddinggemma-300M-Q8_0.gguf` | Embedding notes and questions (vector search) | [`google/embeddinggemma-300m`](https://huggingface.co/google/embeddinggemma-300m) | [Gemma Terms of Use](https://ai.google.dev/gemma/terms) and the [Gemma Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy) |
| [`tobil/qmd-query-expansion-1.7B-gguf`](https://huggingface.co/tobil/qmd-query-expansion-1.7B-gguf), file `qmd-query-expansion-1.7B-q4_k_m.gguf` | Rewriting a question into search variants | [`Qwen/Qwen3-1.7B`](https://huggingface.co/Qwen/Qwen3-1.7B) (Apache-2.0) | MIT (per its model card) |
| [`ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`](https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF), file `qwen3-reranker-0.6b-q8_0.gguf` | Reranking results (hybrid `query` only) | [`Qwen/Qwen3-Reranker-0.6B`](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) | Apache-2.0 |

Notes:

- **EmbeddingGemma.** Google's model card lists the license as `gemma`. The ggml-org GGUF
  conversion's card states no license of its own. As a conversion of Google's model it
  remains subject to the Gemma Terms of Use, which also bind anyone using the model to the
  Gemma Prohibited Use Policy.
- **Query expansion.** The card for this fine-tune of Qwen3-1.7B lists MIT. The base model,
  Qwen3-1.7B, is Apache-2.0.
- **Reranker.** Both the GGUF conversion and Qwen's original model list Apache-2.0.
