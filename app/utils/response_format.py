from typing import Any, Optional

from pydantic import BaseModel


class Result(BaseModel):
    data: Optional[Any] = None
    status: int
    message: str
    isSuccess: bool

    def __init__(self, **data):
        data["isSuccess"] = data.get("status", 500) // 100 == 2
        super().__init__(**data)
