from typing import Literal

from pydantic import BaseModel, Field


class MediaAsset(BaseModel):
    asset_id: str = Field(min_length=1)
    creator_id: str = Field(min_length=1)
    media_kind: Literal["audio", "video"]
    deidentified_transcript: str = Field(min_length=1, max_length=4000)


class ProcessingJobRequest(BaseModel):
    asset: MediaAsset
    delivery_channel: Literal["creator_portal", "secure_review_queue"]
    max_call_cost_usd: float = Field(gt=0)
    expected_output_tokens: int = Field(default=300, ge=32, le=2000)


class CreatorDelivery(BaseModel):
    job_id: str
    asset_id: str
    state: Literal["delivered", "held_for_review"]
    estimated_cost_usd: float
    actual_cost_usd: float | None = None
    served_by: str | None = None
    creator_summary: str | None = None
