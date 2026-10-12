import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from media_cost.creator_delivery import process_for_creator
from media_cost.infrai_gateway import InfraiError, InfraiGateway
from media_cost.models import CreatorDelivery, ProcessingJobRequest


def gateway_from_environment() -> InfraiGateway:
    return InfraiGateway(os.environ["INFRAI_API_KEY"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    gateway = gateway_from_environment()
    app.state.infrai = gateway
    hard_cap = float(os.environ.get("INFRAI_HARD_CAP_USD", "25"))
    alert_at = float(os.environ.get("INFRAI_ALERT_THRESHOLD_USD", "20"))
    await gateway.set_monthly_budget(hard_cap, alert_at)
    yield
    await gateway.close()


app = FastAPI(title="Private media call cost", lifespan=lifespan)


@app.post("/processing-jobs", response_model=CreatorDelivery)
async def create_processing_job(job: ProcessingJobRequest) -> CreatorDelivery:
    try:
        return await process_for_creator(job, app.state.infrai)
    except InfraiError as exc:
        client_status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(
            status_code=client_status,
            detail={"code": exc.code, "details": exc.details},
        ) from exc
