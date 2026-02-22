import json
from typing import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.orchestrator import orchestrator
from app.schemas.detect import SimulateRequest, SimulateResponse
from app.services.opinion_simulation import simulate_opinion_stream

router = APIRouter(prefix="/simulate", tags=["simulate"])


@router.post("", response_model=SimulateResponse)
def simulate(payload: SimulateRequest) -> SimulateResponse:
    result = orchestrator.run_simulation(
        text=payload.text,
        time_window_hours=payload.time_window_hours,
        platform=payload.platform,
        comments=payload.comments,
        claims=payload.claims,
        evidences=payload.evidences,
        report=payload.report,
    )
    return result


@router.post("/stream")
def simulate_stream(payload: SimulateRequest) -> StreamingResponse:
    """SSE 流式返回舆情预演结果，每完成一个阶段推送一次"""

    def event_generator() -> Iterator[str]:
        for chunk in simulate_opinion_stream(
            text=payload.text,
            claims=payload.claims,
            evidences=payload.evidences,
            report=payload.report,
            time_window_hours=payload.time_window_hours,
            platform=payload.platform,
            comments=payload.comments,
        ):
            data = json.dumps(chunk, ensure_ascii=False)
            yield f"data: {data}\n\n"

    return StreamingResponse(
        iter(event_generator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )
