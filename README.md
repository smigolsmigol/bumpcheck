# Bumpcheck

[![CI](https://github.com/smigolsmigol/bumpcheck/actions/workflows/ci.yml/badge.svg)](https://github.com/smigolsmigol/bumpcheck/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/smigolsmigol/bumpcheck/graph/badge.svg)](https://codecov.io/gh/smigolsmigol/bumpcheck)
[![PyPI](https://img.shields.io/pypi/v/bumpcheck.svg)](https://pypi.org/project/bumpcheck/)
[![Python versions](https://img.shields.io/pypi/pyversions/bumpcheck.svg)](https://pypi.org/project/bumpcheck/)
[![License](https://img.shields.io/github/license/smigolsmigol/bumpcheck.svg)](LICENSE)

Replay one application contract before and after a dependency bump. Bumpcheck
exits nonzero when returned JSON, Pydantic validation errors, warnings, or
captured output change.

## Quickstart

[Install uv](https://docs.astral.sh/uv/getting-started/installation/), then save
the behavior your application depends on as `contract.py`:

```python
from collections.abc import Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

MetadataKey = Annotated[str, Field(max_length=3)]


class Model(BaseModel):
    model_config = ConfigDict(strict=True)
    metadata: Mapping[MetadataKey, str]


def run():
    return Model(metadata={"toolong": "b"}).model_dump(mode="json")
```

Run it against two versions. `uvx` fetches Bumpcheck, so there is no separate
tool installation step:

```console
$ uvx bumpcheck check contract.py \
    --baseline pydantic==2.10.6 \
    --candidate pydantic==2.11.1 \
    --python-version 3.12
BASELINE pydantic=2.10.6, pydantic-core=2.27.2 @ .../python
CANDIDATE pydantic=2.11.1, pydantic-core=2.33.0 @ .../python
CHANGED contract: ValidationError[string_too_long] -> return {"metadata":{"toolong":"b"}}
```

This reproduces [pydantic/pydantic#11681](https://github.com/pydantic/pydantic/issues/11681).
Exit code 0 means unchanged, 1 means behavior changed, and 2 means the capture
was not trustworthy. Install a persistent command with
`uv tool install bumpcheck` if you prefer it over `uvx`.

## GitHub Actions

Run Bumpcheck from PyPI and install the checkout into both comparison
environments:

```yaml
jobs:
  bumpcheck:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0
        with:
          enable-cache: true
          python-version: "3.12"
          version: 0.12.5
      - run: |
          uvx --from bumpcheck==0.2.1 \
            bumpcheck check contract.py \
            --baseline pydantic==2.10.6 \
            --candidate pydantic==2.11.1 \
            --with . \
            --python-version 3.12
```

[Tracewright's Pydantic compatibility job](https://github.com/smigolsmigol/tracewright/blob/1d7d22eb2f0e1e06a2b47dbf8f858da447cf6b61/.github/workflows/ci.yml#L14-L39)
uses this pattern to replay four JSON Lines fixture inputs against two Pydantic
versions.

## Check your application

A contract is a normal Python file exposing either `run()` or `run(value)`.
Return a JSON-compatible value that represents the behavior your application
depends on.

Use `--with .` to install the current project into both isolated environments:

```console
bumpcheck check contract.py \
  --baseline pydantic==2.10.6 \
  --candidate pydantic==2.11.1 \
  --with .
```

Repeat `--with` for shared dependencies. Use `--watch DIST[:MODULE]` to add to
the default `pydantic` and `pydantic-core` provenance. Use `--only-watch`
instead when the named distributions should replace those defaults.

For example, the issue-derived integration suite detects the
[`Path / Path` fix in Monty](https://github.com/pydantic/monty/pull/621):

```console
bumpcheck check examples/regressions/monty_path_join.py \
  --baseline pydantic-monty==0.0.19 \
  --candidate pydantic-monty==0.0.20 \
  --only-watch pydantic-monty:pydantic_monty
```

For real payloads, define `run(value)` and pass `--inputs`. Bumpcheck accepts a
JSON array, `.jsonl` or `.ndjson`, or a Pydantic Evals JSON document containing
a `cases` array. It preserves case names or JSON Lines source line numbers and
hashes the case and input bytes before comparing results.

If environments already exist, use `--baseline-python` and
`--candidate-python` instead of requirement targets. Use `--json` for a
machine-readable report and `--exact` when warning messages, exception messages,
stdout, and stderr must also match.

## Scope and limits

Bumpcheck is a focused pre-upgrade gate, not a test runner or an API/schema
diff. It is useful for data-dependent validation and serialization behavior
that ordinary dependency tooling does not observe.

Cases are trusted code. The subprocess boundary enforces a timeout but is not a
security sandbox. Receipts contain local interpreter and module paths, so review
JSON output before sharing it. Imported project files are not hashed; run from
an immutable revision when they are part of the contract.

## Migration

Bumpcheck was previously named Pydantic Canary. The `bumpcheck` distribution
installs a temporary `pydantic-canary` command alias, but new code should import
`bumpcheck` and use the `bumpcheck` command.

## Development

```console
uv run --isolated --no-project --no-config --no-cache --with . -- \
  python -B -m unittest discover -s tests -v
uv run --isolated --no-project --no-config --with ruff==0.16.4 -- ruff check .
uv build
```
