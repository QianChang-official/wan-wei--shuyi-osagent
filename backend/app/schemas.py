from pydantic import BaseModel
from typing import Any
class MemoryEventIn(BaseModel):
    source_type: str
    scene: str='general'
    content: dict[str, Any]
class ForgetPreviewIn(BaseModel):
    instruction: str
    scope: str='current_user'
class ForgetConfirmIn(BaseModel):
    forget_request_id: str
    confirm: bool=True
    mode: str='cascade'
