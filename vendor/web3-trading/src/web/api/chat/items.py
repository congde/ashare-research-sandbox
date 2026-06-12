# -*- coding: utf-8 -*-
'''
@Time    :   2025/11/09 17:39:24
'''
from typing import Optional
from enum import StrEnum

from pydantic import BaseModel, Field


class ExtraBodyModel(BaseModel):
    # eventId: Optional[str] = Field(None, description="主动触达的事件ID")
    # eventSummary: str = Field("", description="主动触达的事件摘要")
    
    model_config = {
        "extra": "allow"
    }
