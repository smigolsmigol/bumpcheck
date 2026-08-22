"""Pydantic issue 12379: serialize_as_any bypassed a field serializer in 2.12.0."""

from pydantic import BaseModel, ConfigDict, SerializationInfo, field_serializer


class ArrayLike:
    def __init__(self, values):
        self.values = values


class Model(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    value: ArrayLike

    @field_serializer("value")
    def serialize_value(self, value: ArrayLike, info: SerializationInfo):
        return value.values


def run():
    model = Model(value=ArrayLike([1, 2, 3]))
    return model.model_dump(mode="json", serialize_as_any=True)
