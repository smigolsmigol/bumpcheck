"""Pydantic Settings issue 785: nested dict environment values must parse."""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    nested_field: dict[str, str]
    model_config = SettingsConfigDict(env_nested_delimiter="__")


def run():
    os.environ["NESTED_FIELD__KEY"] = "some value"
    return Settings().model_dump(mode="json")
