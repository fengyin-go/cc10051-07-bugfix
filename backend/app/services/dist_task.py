"""分发任务领域服务：管理把发布版本分发给订阅方的批次调度、送达确认与失败重试，完成导出动作。

数据链路位置：主数据分发层执行端，负责消费发布版本与订阅过滤，
把送达回执写入回执中心。

修复点：
- 每个分发批次携带发件凭证号、发件版本、实际发出行数，作为回执核验基准；
- 分发任务只依据属于自己（批次 + 订阅方联合键）的签收回执结算，
  其他订阅方报缺件/差异不得把本批次的成功发放冲销成失败；
- 结算时把登记状态与发件凭证关联后交回回执中心。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DistTaskService(BaseModuleService):
    MODULE = "dist_task"
    ENTITY = "分发批次"
    OPERATION_TERM = "导出"
    LIST_FIELDS = [
        "分发批次", "订阅方", "记录范围", "发件版本", "发件行数",
        "发件凭证号", "分发状态", "回执状态",
    ]
    REQUIRED_FIELDS = ["分发批次", "订阅方", "记录范围"]
    STATUS_ORDER = ["排队中", "分发中", "已送达", "分发失败"]
    ACTION_RULES = {"开始分发": "分发中", "重试分发": "分发失败"}
    NEGATIVE_ACTIONS = []

    # ---- 业务扩展：版本分发与回执回收 ----

    def dispatch_batch(self, entry_id: int) -> dict[str, Any]:
        """执行分发：校验订阅方生效后置为分发中，并固化发件凭证口径。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "分发批次不存在"}
        subscriber = entry.get("订阅方", "")
        sub = next((s for s in store.rows("subscriber_mgr")
                    if s.get("订阅方标识") == subscriber), None)
        if sub is None or sub.get("status") != "已生效":
            return {"ok": False, "message": f"订阅方 {subscriber} 未生效，拒绝分发"}
        entry["status"] = "分发中"
        entry["分发状态"] = "分发中"
        entry["pending"] = True
        # 发件时固化版本与行数，回执必须按这个口径核验
        entry.setdefault("发件版本", str(entry.get("记录范围", "")).replace("版本 ", ""))
        entry.setdefault("发件行数", 0)
        if not entry.get("发件凭证号"):
            entry["发件凭证号"] = f"DV-{entry.get('分发批次', entry_id)}-{entry_id}"
        return {"ok": True, "subscriber": subscriber, "scope": entry.get("记录范围"),
                "dispatch_voucher": entry.get("发件凭证号")}

    def confirm_delivery(self, entry_id: int) -> dict[str, Any]:
        """确认送达：登记发件凭证并向回执中心开立待签收来件（不直接核销）。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "分发中":
            return {"ok": False, "message": "批次不在分发中状态"}
        entry["status"] = "已送达"
        entry["分发状态"] = "已送达"
        entry["回执状态"] = "待签收"
        entry["pending"] = False
        if not entry.get("发件凭证号"):
            entry["发件凭证号"] = f"DV-{entry.get('分发批次', entry_id)}-{entry_id}"

        receipts = store.rows("dist_receipt")
        receipt_id = max((int(r.get("id", 0)) for r in receipts), default=0) + 1
        receipts.append({
            "id": receipt_id,
            "回执编号": f"rc-{entry_id}-{receipt_id}",
            "分发批次": entry.get("分发批次", ""),
            "订阅方": entry.get("订阅方", ""),
            # 实际收件主体与分发批次联合决定签收资格
            "实际收件主体": entry.get("订阅方", ""),
            "签收凭证号": "",
            "签收版本": "",
            "签收行数": None,
            "核销凭据号": "",
            "关联分发任务": entry_id,
            "发件凭证号": entry.get("发件凭证号", ""),
            "处理阶段": "待签收",
            "差异类型": "",
            "回执状态": "未回收",
            "差异说明": "",
            "status": "未回收",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "receipt_id": receipt_id,
                "dispatch_voucher": entry.get("发件凭证号")}

    def settle_by_receipt(self, entry_id: int) -> dict[str, Any]:
        """分发任务据签收回执结算自己发出的版本和实际行数。

        只认属于本任务（分发批次 + 订阅方联合键）且已核销的回执；
        其他订阅方同批次的差异/缺件与本任务无关，不会冲销本任务的成功发放。
        结算后把登记状态与发件凭证关联，交回回执中心。
        """
        task = store.find(self.MODULE, entry_id)
        if task is None:
            return {"ok": False, "message": "分发批次不存在"}

        batch = task.get("分发批次", "")
        subscriber = task.get("订阅方", "")
        receipt = next(
            (r for r in store.rows("dist_receipt")
             if r.get("分发批次") == batch
             and r.get("实际收件主体") == subscriber
             and r.get("处理阶段") == "已核销"),
            None,
        )
        if receipt is None:
            return {"ok": False, "message": "缺少属于本批次本主体的已核销签收回执，暂不结算"}

        # 版本与行数二次核验：以原发件口径为准
        if receipt.get("签收版本") and task.get("发件版本") \
                and str(receipt.get("签收版本")) != str(task.get("发件版本")):
            return {"ok": False,
                    "message": f"结算核验失败：签收版本 {receipt.get('签收版本')} "
                               f"≠ 发件版本 {task.get('发件版本')}"}
        if receipt.get("签收行数") not in (None, "") and task.get("发件行数") not in (None, ""):
            if int(receipt.get("签收行数")) != int(task.get("发件行数")):  # type: ignore[arg-type]
                return {"ok": False,
                        "message": f"结算核验失败：签收行数 {receipt.get('签收行数')} "
                                   f"≠ 发件行数 {task.get('发件行数')}"}

        task["status"] = "已送达"
        task["分发状态"] = "已送达"
        task["回执状态"] = "已回收"
        task["核销凭据号"] = receipt.get("核销凭据号")
        task["关联回执编号"] = receipt.get("回执编号")
        task["实际签收行数"] = receipt.get("签收行数")
        task["pending"] = False
        task["abnormal"] = False
        task["结算时间"] = datetime.now(timezone.utc).isoformat()
        # 回执侧回写发件凭证关联，完成「交回回执中心」闭环
        receipt["发件凭证号"] = task.get("发件凭证号", receipt.get("发件凭证号", ""))
        receipt["关联分发任务"] = entry_id
        return {
            "ok": True,
            "message": "分发任务已按签收回执结算，登记状态与发件凭证已关联",
            "dispatch_task_id": entry_id,
            "dispatch_voucher": task.get("发件凭证号"),
            "writeoff_token": receipt.get("核销凭据号"),
            "receipt_id": receipt.get("id"),
            "signed_rows": receipt.get("签收行数"),
        }

    def fail_and_requeue(self, entry_id: int, reason: str) -> dict[str, Any]:
        """标记分发失败，保留断点供重试。仅本任务自身失败时调用。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "分发批次不存在"}
        entry["status"] = "分发失败"
        entry["分发状态"] = "分发失败"
        entry["abnormal"] = True
        entry["失败原因"] = reason
        return {"ok": False, "message": f"分发失败: {reason}", "retryable": True}

    def consume_publish_scope(self, entry_id: int) -> dict[str, Any] | None:
        """读取发布模块的版本范围，校验分发覆盖。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        scope = str(entry.get("记录范围", "")).replace("版本 ", "")
        return next((p for p in store.rows("golden_publish")
                     if p.get("版本标识") == scope), None)

    def resolve_backlog(self, entry_id: int) -> int:
        """按发布批次聚合积压分发任务数。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return 0
        scope = str(entry.get("记录范围", "")).replace("版本 ", "")
        return sum(1 for t in store.rows(self.MODULE)
                   if str(t.get("记录范围", "")).endswith(scope)
                   and t.get("status") in ("排队中", "分发中"))

    def notify_subscriber_rollback(self, entry_id: int, new_version: str) -> str:
        """回滚后通知订阅方新版本口径。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return "分发批次不存在"
        subscriber = entry.get("订阅方", "")
        for sub in store.rows("subscriber_mgr"):
            if sub.get("订阅方标识") == subscriber:
                sub["pending"] = True
        entry["记录范围"] = f"版本 {new_version}"
        entry["发件版本"] = new_version
        entry["status"] = "排队中"
        entry["pending"] = True
        return f"已通知 {subscriber} 切换到 {new_version}"
