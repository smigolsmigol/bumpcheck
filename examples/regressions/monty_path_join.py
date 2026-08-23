"""Monty PR 621: Path / Path composition failed before pydantic-monty 0.0.20."""

from pydantic_monty import Monty


def run():
    code = "from pathlib import Path\nstr(Path('reports') / Path('result.json'))"
    with Monty() as pool, pool.checkout() as session:
        return session.feed_run(code)
