"""Harness issue 511: high-entropy binary media must round-trip unchanged."""

import asyncio
import json
import tempfile

from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.messages import BinaryContent, ModelRequest, UserPromptPart
from pydantic_ai_harness.media import DiskMediaStore, externalize_media, restore_media


async def _round_trip():
    payload = bytes(range(256)) * 500
    messages = [
        ModelRequest(
            parts=[
                UserPromptPart(
                    content=[
                        "look at this",
                        BinaryContent(data=payload, media_type="application/octet-stream"),
                    ]
                )
            ]
        )
    ]
    node = json.loads(ModelMessagesTypeAdapter.dump_json(messages))

    with tempfile.TemporaryDirectory() as directory:
        store = DiskMediaStore(directory=directory)
        lean = await externalize_media(node, media_store=store, threshold_bytes=64 * 1024)
        full = await restore_media(lean, media_store=store)

    restored = ModelMessagesTypeAdapter.validate_python(full)
    binary = restored[0].parts[0].content[1]
    return {"matches": binary.data == payload, "size": len(binary.data)}


def run():
    return asyncio.run(_round_trip())
