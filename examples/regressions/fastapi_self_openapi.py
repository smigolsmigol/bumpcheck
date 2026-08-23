"""FastAPI discussion 14341: recursive Self models must produce OpenAPI."""

from typing import Self

from fastapi import FastAPI
from pydantic import BaseModel


class Node(BaseModel):
    id: str
    children: list[Self]


app = FastAPI()


@app.get("/node", response_model=Node)
def get_node():
    return Node(id="root", children=[])


def run():
    schema = app.openapi()
    node = schema["components"]["schemas"]["Node"]
    return {"properties": sorted(node["properties"]), "required": node["required"]}
