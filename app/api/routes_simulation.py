"""模拟系统API路由"""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

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

router = APIRouter(prefix="/api/simulation", tags=["模拟"])


@router.post("/start", response_model=SimulationStartResponse)
async def start_simulation(request: SimulationStartRequest):
    """启动模拟"""
    simulation_id = f"sim-{uuid.uuid4().hex[:12]}"

    # 创建模拟记录，后续由后台任务执行
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

    return SimulationStartResponse(
        simulation_id=simulation_id,
        status="pending",
        message="模拟已创建，等待执行"
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
    if sim.status == SimulationStatus.RUNNING:
        progress = 0.5  # TODO: 实时计算
    elif sim.status == SimulationStatus.COMPLETED:
        progress = 1.0

    return SimulationStatusResponse(
        simulation_id=simulation_id,
        status=sim.status.value,
        progress=progress,
        message=f"当前状态: {sim.status.value}"
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


@router.delete("/{simulation_id}")
async def delete_simulation(simulation_id: str):
    """删除模拟"""
    storage = get_simulation_storage()
    success = storage.delete_simulation(simulation_id)

    if not success:
        raise HTTPException(status_code=404, detail="模拟不存在")

    return {"message": "删除成功"}
