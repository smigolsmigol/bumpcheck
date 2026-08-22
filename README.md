# Pydantic Canary

Pydantic Canary is an independent proof of concept. It runs one application
contract against two Python environments and shows only the Pydantic behavior
that changed, with proof of which installations ran.

```console
$ pydantic-canary check examples/regressions/instructor_partial_stream.py \
    --inputs examples/inputs/instructor_stream.json \
    --baseline pydantic==2.11.7 \
    --candidate pydantic==2.12.0 \
    --with instructor==1.9.2
BASELINE pydantic=2.11.7 @ .../site-packages/pydantic/__init__.py
CANDIDATE pydantic=2.12.0 @ .../site-packages/pydantic/__init__.py
CHANGED instructor_partial_stream: 1/2 inputs; first empty-initial-chunk: return {"value":null} -> ValidationError[missing]
```

The short form uses `uv` to create isolated, ephemeral environments. Existing
locked environments can be checked with `--baseline-python` and
`--candidate-python` instead. Requirement targets use the controller's Python
minor version by default. Pass `--python-version` to test another interpreter.
Canary never installs itself into either target.

This catches runtime drift that an API diff or JSON Schema comparison cannot
see. A case is a normal Python file with a JSON-compatible `run()` result:

```python
from pydantic import BaseModel


class User(BaseModel):
    age: int


def run():
    return User.model_validate({"age": "42"}).model_dump(mode="json")
```

To replay real payloads, define `run(value)` and pass `--inputs`. The input file
can be a JSON array, a `.jsonl` or `.ndjson` file, or a Pydantic Evals JSON
dataset with a `cases` array. Evals case names and JSON Lines source line
numbers are preserved in the report. Canary hashes both the case and input
bytes and rejects a comparison if either changed between runs.

Exit code 0 means unchanged, 1 means behavior changed, and 2 means the capture
was not trustworthy. A dependency-update job can therefore use the command as
a direct CI gate.

## Why another compatibility check?

Existing Pydantic gates solve different parts of an upgrade:

| Gate | What it proves |
| --- | --- |
| Griffe and API checks | Public names and signatures remain compatible |
| JSON Schema snapshots and `stable_pydantic` | Model contracts and stored schemas remain compatible |
| `bump-pydantic` | Source can be migrated from Pydantic V1 to V2 |
| Consumer test matrices | Full projects still pass their asserted tests |
| Pydantic Canary | Selected runtime behavior is unchanged across two exact environments |

Canary is a narrow gate before a dependency upgrade, not a replacement for a
test suite. It is useful when the risky behavior is data-dependent, only partly
asserted, or hidden behind validation and serialization internals.

## Current evidence

The POC distinguishes three public regressions:

- strict mapping-key validation in Pydantic 2.10.6 versus 2.11.1
- modified `FieldInfo` defaults in 2.11.7 versus 2.12.0
- `field_serializer` with `serialize_as_any=True` in 2.11.9 versus 2.12.0

The `FieldInfo` case also runs through Instructor 1.9.2's public partial
streaming path. Under the same Python 3.12 interpreter and Instructor version,
one named payload returns a partial model on the baseline and raises Pydantic's
stable `missing` error type on the candidate. A complete-payload control remains
unchanged in the same run.

Canary also reports no change for identical and compatible patch environments,
rejects missing watched packages, and stops a case that exceeds its timeout.

## Limits

Canary does not run pytest or replace project tests. Input replay currently
accepts JSON and JSON Lines, not YAML. The receipt hashes the case and input files, but not
Python modules imported by the case. Run from an immutable revision when those
imports are part of the contract. `--timeout` covers environment setup and case
execution together.

Cases are trusted code. The subprocess boundary limits faults and enforces a
timeout, but it is not a security sandbox. JSON receipts include local
interpreter and module paths, so review them before sharing.

## Development

The controller requires Python 3.10 or later and has no runtime dependencies.
The worker is Python 3.9 compatible and does not need Canary installed in the
target environments.

```console
python -m venv .venv
.venv/bin/python -m pip install -e .
PYTHONPATH=src .venv/bin/python -m unittest discover -v
```
