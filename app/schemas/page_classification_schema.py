from typing import List
from pydantic import BaseModel, Field


class PageClassification(BaseModel):
    page_index: int = Field(
        ..., 
        description="0-based index of the page analyzed."
    )
    is_commercial: bool = Field(
        ...,
        description=(
            "True if the page contains ANY commercial quotation items, unit rates, "
            "totals, taxes, or fees. False if strictly legal terms, blank forms, or technical datasheets."
        ),
    )
    reason: str = Field(
        ...,
        description=(
            "Brief explanation for the classification (e.g. 'Contains line items and tax breakdown')."
        ),
    )


class DocumentClassificationResult(BaseModel):
    pages: List[PageClassification] = Field(
        default_factory=list,
        description="List of classifications for all analyzed pages.",
    )