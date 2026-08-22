"""Pydantic issue 12360: create_model lost a modified FieldInfo default in 2.12.0."""

from copy import deepcopy

from pydantic import Field, create_model


def run():
    original_field = Field(..., description="Required field")
    field = deepcopy(original_field)
    field.annotation = str | None
    field.default = None
    model = create_model("TestModel", response=(field.annotation, field))
    return model.model_validate({}).model_dump(mode="json")
