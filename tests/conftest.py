from collections.abc import Iterator

import pytest
from intake_mcp import LocalProfile


@pytest.fixture
def profile() -> Iterator[LocalProfile]:
    local = LocalProfile()
    yield local
    local.reset()


def fill_required_fields(
    profile: LocalProfile,
    conversation_key: str,
    *,
    command_prefix: str = "fill",
) -> tuple[str, int]:
    context = profile.get_intake_context(conversation_key)
    assert context.ok and context.data is not None
    request_id = str(context.data["requestId"])
    revision = int(context.data["requestRevision"])
    values = {
        "title": "New finance portal",
        "business_need": "Replace the unsupported finance request workflow.",
        "urgency": "high",
        "budget": "25000",
    }
    for index, (field_path, value) in enumerate(values.items()):
        result = profile.update_intake_field(
            request_id,
            revision,
            f"{command_prefix}-{index}",
            field_path,
            value,
            f"message:{index}",
            0.95,
        )
        assert result.ok and result.data is not None
        revision = int(result.data["requestRevision"])
    return request_id, revision

