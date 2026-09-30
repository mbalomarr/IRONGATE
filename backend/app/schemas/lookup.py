from typing import Optional

from pydantic import BaseModel


class LookupOut(BaseModel):
    id: Optional[int] = None
    code: str
    name: str
