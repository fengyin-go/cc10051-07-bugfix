"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class SignoffPayload(BaseModel):
    """来件详情提交实际签收归属与签收凭证。"""
    operator: str
    实际收件主体: str | None = None
    签收凭证号: str | None = None
    签收版本: str | None = None
    签收行数: int | None = None
    差异说明: str | None = None


class ReturnPayload(BaseModel):
    operator: str
    reason: str = ""


class CorrectionPayload(BaseModel):
    operator: str
    更正凭证号: str | None = None
    更正说明: str | None = None
    原签收凭证号: str | None = None
    关联分发任务: int | None = None


class CorrectionReviewPayload(BaseModel):
    decision: str  # accept / reject
    note: str | None = None


class CorrectionResubmitPayload(BaseModel):
    operator: str
    更正凭证号: str
    更正说明: str | None = None
