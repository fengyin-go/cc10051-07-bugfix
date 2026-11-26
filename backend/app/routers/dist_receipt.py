"""分发回执中心专用路由：来件详情、签收核对、更正受理、分发任务结算。

与通用资源路由（/api/{module}）并存，路径更具体，须先于通用路由注册。
所有写操作都带 operator（值班员/订阅方标识），服务端据此做权限收敛：
订阅方只能查看/操作本主体来件，X 仍只由 A 核销。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    CorrectionPayload,
    CorrectionResubmitPayload,
    CorrectionReviewPayload,
    ReturnPayload,
    SignoffPayload,
)
from app.services.dist_receipt import DistReceiptService
from app.services.dist_task import DistTaskService

router = APIRouter(prefix="/api/dist_receipt", tags=["分发回执中心"])

receipt_service = DistReceiptService()
task_service = DistTaskService()


@router.get("/incoming")
def list_incoming(
    operator: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """来件列表；带 operator 时只返回该主体有权查看的来件。"""
    items, total = receipt_service.list_entries(
        status=status, page=page, size=size, operator=operator)
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/incoming/{entry_id}")
def incoming_detail(entry_id: int, operator: str | None = Query(default=None)) -> dict[str, Any]:
    """来件详情按权限开放；附带本件更正单状态供值班员核对。"""
    entry = receipt_service.get_entry(entry_id, operator=operator)
    if entry is None:
        raise HTTPException(status_code=404, detail="来件不存在或无权查看")
    correction = receipt_service.correction_status(entry_id)
    return {"entry": entry, "correction": correction}


@router.post("/incoming/{entry_id}/signoff")
def submit_signoff(entry_id: int, payload: SignoffPayload) -> dict[str, Any]:
    """操作员在来件详情提交实际签收归属，服务端核验后返回签收核销凭据。"""
    result = receipt_service.submit_signoff(entry_id, payload.operator, payload.model_dump())
    if not result.get("ok"):
        # 业务核验不通过（资格/版本/行数不符）返回 200 结构，前端按 code 分流
        result["http_hint"] = 422 if result.get("code") in (
            "not_eligible", "verify_rejected", "forbidden", "bad_request") else 400
    return result


@router.post("/incoming/{entry_id}/return")
def mark_return(entry_id: int, payload: ReturnPayload) -> dict[str, Any]:
    """订阅方收件时退回来件（区别于分发核验时驳回）。"""
    return receipt_service.mark_recipient_return(entry_id, payload.operator, payload.reason)


@router.post("/incoming/{entry_id}/corrections")
def submit_correction(entry_id: int, payload: CorrectionPayload) -> dict[str, Any]:
    """订阅方以错填原件为依据，从自己的来件详情提交更正。"""
    return receipt_service.submit_correction(entry_id, payload.operator, payload.model_dump())


@router.get("/corrections")
def list_corrections(operator: str | None = Query(default=None)) -> dict[str, Any]:
    """更正队列；订阅方只看本主体，值班员看全部。"""
    return {"items": receipt_service.list_corrections(operator)}


@router.post("/corrections/{correction_id}/review")
def review_correction(correction_id: int, payload: CorrectionReviewPayload) -> dict[str, Any]:
    """值班员受理更正或要求补交凭证；受理联动本件分发任务结算。"""
    return receipt_service.review_correction(
        correction_id, payload.decision, payload.note or "")


@router.post("/corrections/{correction_id}/resubmit")
def resubmit_correction(correction_id: int, payload: CorrectionResubmitPayload) -> dict[str, Any]:
    """被要求补交凭证后，申请主体补交凭证重新进入待受理。"""
    return receipt_service.resubmit_correction(
        correction_id, payload.operator, payload.model_dump())


@router.post("/tasks/{task_id}/settle")
def settle_task(task_id: int) -> dict[str, Any]:
    """分发任务据签收回执结算自己发出的版本和实际行数。"""
    return task_service.settle_by_receipt(task_id)
