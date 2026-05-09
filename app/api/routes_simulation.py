"""模拟系统API路由"""

import uuid
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.schemas.simulation import (
    SimulationStartRequest,
    SimulationStartResponse,
    SimulationStatusResponse,
    SimulationResultResponse,
)
from app.services.simulation.storage import get_simulation_storage
from app.services.simulation.models import (
    Simulation,
    SimulationStatus,
    Platform,
    SimulationMode,
)
from app.services.simulation.simulation_engine import SimulationEngine

router = APIRouter(prefix="/api/simulation", tags=["模拟"])

# 存储活跃的模拟引擎实例
_active_engines: dict[str, SimulationEngine] = {}


@router.post("/start", response_model=SimulationStartResponse)
async def start_simulation(request: SimulationStartRequest):
    """启动模拟"""
    simulation_id = f"sim-{uuid.uuid4().hex[:12]}"

    # 创建模拟记录
    storage = get_simulation_storage()

    sim = Simulation(
        id=simulation_id,
        name=request.name or f"模拟_{simulation_id[:8]}",
        description=request.description,
        mode=request.mode,
        agent_count=request.agent_count,
        platforms=request.platforms,
        duration=request.duration,
        seed_content=request.seed_content or "",
        status=SimulationStatus.PENDING,
    )

    storage.save_simulation(sim)

    # 创建引擎实例
    engine = SimulationEngine(
        simulation_id=simulation_id,
        agent_count=request.agent_count,
        platforms=request.platforms,
        duration=request.duration,
        seed_content=request.seed_content or "",
        seed=request.seed,
    )
    _active_engines[simulation_id] = engine

    return SimulationStartResponse(
        simulation_id=simulation_id,
        status="pending",
        message="模拟已创建，等待执行"
    )


@router.get("/{simulation_id}/stream")
async def stream_simulation_progress(simulation_id: str):
    """
    SSE流式返回模拟进度

    使用Server-Sent Events实时推送模拟进度
    """
    storage = get_simulation_storage()
    sim = storage.get_simulation(simulation_id)

    if not sim:
        raise HTTPException(status_code=404, detail="模拟不存在")

    # 获取或创建引擎
    engine = _active_engines.get(simulation_id)
    if not engine:
        engine = SimulationEngine(
            simulation_id=simulation_id,
            agent_count=sim.agent_count,
            platforms=sim.platforms,
            duration=sim.duration,
            seed_content=sim.seed_content,
        )
        _active_engines[simulation_id] = engine

    async def event_generator():
        """SSE事件生成器"""
        try:
            # 更新状态为运行中
            sim.status = SimulationStatus.RUNNING
            storage.save_simulation(sim)

            # 流式返回进度
            async for progress in engine.run_with_progress():
                # SSE格式: data: {json}\n\n
                event_data = {
                    "simulation_id": progress.simulation_id,
                    "tick": progress.tick,
                    "total_ticks": progress.total_ticks,
                    "progress": progress.progress,
                    "current_hour": progress.current_hour,
                    "current_day": progress.current_day,
                    "status": progress.status,
                    "message": progress.message,
                }
                yield f"data: {event_data}\n\n"

                # 如果完成或取消，结束流
                if progress.status in ["completed", "cancelled"]:
                    break

            # 获取最终结果
            result = engine.get_intermediate_result()

            # 更新模拟记录
            sim.status = SimulationStatus.COMPLETED
            sim.result = result
            from datetime import datetime
            sim.completed_at = datetime.now()
            storage.save_simulation(sim)

            # 发送最终结果事件
            final_event = {
                "simulation_id": simulation_id,
                "status": "completed",
                "result": {
                    "sentiment_distribution": result.sentiment_distribution,
                    "opinion_clusters": result.opinion_clusters,
                    "trigger_points": result.trigger_points,
                    "risk_warnings": result.risk_warnings,
                    "suggestions": result.suggestions,
                }
            }
            yield f"event: result\ndata: {final_event}\n\n"

        except Exception as e:
            # 错误处理
            error_event = {
                "simulation_id": simulation_id,
                "status": "error",
                "message": str(e),
            }
            yield f"event: error\ndata: {error_event}\n\n"

            # 更新状态
            sim.status = SimulationStatus.FAILED
            storage.save_simulation(sim)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/{simulation_id}/status", response_model=SimulationStatusResponse)
async def get_simulation_status(simulation_id: str):
    """获取模拟状态"""
    storage = get_simulation_storage()
    sim = storage.get_simulation(simulation_id)

    if not sim:
        raise HTTPException(status_code=404, detail="模拟不存在")

    # 计算进度
    progress = 0.0
    message = f"当前状态: {sim.status.value}"

    # 如果有活跃引擎，获取实时进度
    engine = _active_engines.get(simulation_id)
    if engine:
        progress = engine.timeline.progress
        message = f"正在模拟第{engine.timeline.current_day + 1}天，进度{progress*100:.1f}%"
    elif sim.status == SimulationStatus.COMPLETED:
        progress = 1.0
        message = "模拟已完成"

    return SimulationStatusResponse(
        simulation_id=simulation_id,
        status=sim.status.value,
        progress=progress,
        message=message
    )


@router.get("/{simulation_id}/result", response_model=SimulationResultResponse)
async def get_simulation_result(simulation_id: str):
    """获取模拟结果"""
    storage = get_simulation_storage()
    sim = storage.get_simulation(simulation_id)

    if not sim:
        raise HTTPException(status_code=404, detail="模拟不存在")

    if sim.status != SimulationStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="模拟尚未完成")

    return SimulationResultResponse(
        simulation_id=simulation_id,
        status=sim.status.value,
        result=sim.result,
        created_at=sim.created_at.isoformat(),
        completed_at=sim.completed_at.isoformat() if sim.completed_at else None
    )


@router.get("/list")
async def list_simulations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
):
    """获取模拟列表"""
    storage = get_simulation_storage()
    simulations, total = storage.list_simulations(
        page=page,
        page_size=page_size,
        status=status
    )

    return {
        "list": [
            {
                "id": s.id,
                "name": s.name,
                "status": s.status.value,
                "created_at": s.created_at.isoformat(),
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "agent_count": s.agent_count,
                "platforms": [p.value for p in s.platforms],
            }
            for s in simulations
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/{simulation_id}/pause")
async def pause_simulation(simulation_id: str):
    """暂停模拟"""
    engine = _active_engines.get(simulation_id)
    if not engine:
        raise HTTPException(status_code=404, detail="模拟不存在或未启动")

    engine.pause()
    return {"message": "模拟已暂停", "simulation_id": simulation_id}


@router.post("/{simulation_id}/resume")
async def resume_simulation(simulation_id: str):
    """恢复模拟"""
    engine = _active_engines.get(simulation_id)
    if not engine:
        raise HTTPException(status_code=404, detail="模拟不存在或未启动")

    engine.resume()
    return {"message": "模拟已恢复", "simulation_id": simulation_id}


@router.post("/{simulation_id}/cancel")
async def cancel_simulation(simulation_id: str):
    """取消模拟"""
    engine = _active_engines.get(simulation_id)
    if not engine:
        raise HTTPException(status_code=404, detail="模拟不存在或未启动")

    engine.cancel()

    # 更新状态
    storage = get_simulation_storage()
    sim = storage.get_simulation(simulation_id)
    if sim:
        sim.status = SimulationStatus.FAILED
        storage.save_simulation(sim)

    return {"message": "模拟已取消", "simulation_id": simulation_id}


@router.get("/{simulation_id}/statistics")
async def get_simulation_statistics(simulation_id: str):
    """获取模拟实时统计"""
    engine = _active_engines.get(simulation_id)
    if not engine:
        raise HTTPException(status_code=404, detail="模拟不存在或未启动")

    return engine.get_statistics()


@router.delete("/{simulation_id}")
async def delete_simulation(simulation_id: str):
    """删除模拟"""
    storage = get_simulation_storage()
    success = storage.delete_simulation(simulation_id)

    if not success:
        raise HTTPException(status_code=404, detail="模拟不存在")

    # 清理活跃引擎
    if simulation_id in _active_engines:
        del _active_engines[simulation_id]

    return {"message": "删除成功"}
