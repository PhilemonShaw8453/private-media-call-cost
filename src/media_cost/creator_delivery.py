from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from .models import CreatorDelivery, ProcessingJobRequest


def job_messages(job: ProcessingJobRequest) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Prepare a terse creator delivery note from deidentified media text. "
                "Do not infer identity, diagnosis, or clinical facts."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Media kind: {job.asset.media_kind}\n"
                f"Transcript: {job.asset.deidentified_transcript}"
            ),
        },
    ]


async def process_for_creator(
    job: ProcessingJobRequest, model: Any
) -> CreatorDelivery:
    messages = job_messages(job)
    estimate = await model.estimate_call(messages, job.expected_output_tokens)
    job_id = f"job_{uuid4().hex}"

    if estimate > job.max_call_cost_usd:
        return CreatorDelivery(
            job_id=job_id,
            asset_id=job.asset.asset_id,
            state="held_for_review",
            estimated_cost_usd=estimate,
        )

    summary, actual_cost, vendor = await model.create_summary(messages)
    return CreatorDelivery(
        job_id=job_id,
        asset_id=job.asset.asset_id,
        state="delivered",
        estimated_cost_usd=estimate,
        actual_cost_usd=actual_cost,
        served_by=vendor,
        creator_summary=summary,
    )
