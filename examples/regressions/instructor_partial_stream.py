"""Pydantic issue 12360 through Instructor 1.9.2's public streaming API."""

from instructor.dsl.partial import MakeFieldsOptional, Partial
from pydantic import BaseModel


class Response(BaseModel):
    value: str


def run(chunk="{}"):
    partial_response = Partial[Response, MakeFieldsOptional]
    streamed = list(partial_response.model_from_chunks([chunk]))
    return streamed[-1].model_dump(mode="json")
