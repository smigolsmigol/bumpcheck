"""Pydantic issue 11681: strict Mapping keys skipped max_length in 2.11.1."""

from collections.abc import Mapping
from typing import Annotated

import pydantic

MetadataKey = Annotated[str, pydantic.Field(max_length=50)]


class Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(strict=True)
    metadata: Mapping[MetadataKey, str]


def run():
    return Model(metadata={"a" * 60: "b"}).model_dump(mode="json")
