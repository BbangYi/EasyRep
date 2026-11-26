from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware_timestamp(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return value.astimezone(timezone.utc)


Timestamp = Annotated[datetime, AfterValidator(aware_timestamp)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
