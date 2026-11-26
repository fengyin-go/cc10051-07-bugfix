"""分发回执中心领域服务。

修复点（相对旧实现）：
1. 不再只按「分发批次」单字段匹配，分发任务由 (分发批次, 实际收件主体) 联合定位，
   分发号与实际收件主体共同决定谁有签收资格——B 拿着 A 的分发号不能核销 A 的发放。
2. 签收时版本标识、签收行数必须与原发件一致；只有对应版本和行数的签收才能核销，
   差异归本件处理，不回写、不冲销其他订阅方的分发任务。
3. 相同签收凭证重复送达时查回原核销凭据，已办理的差异不允许二次更正。
4. 更正单（误填原件的纠正依据）独立流转，受理后才联动本件分发任务结算。
5. 分发任务依据签收回执结算自己发出的版本与实际行数，登记状态与发件凭证关联后
   交回执中心，回执中心按权限开放来件详情。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 更正单状态
CORRECTION_PENDING = "待受理"
CORRECTION_ACCEPTED = "已受理"
CORRECTION_REJECTED = "需补交凭证"
CORRECTION_DONE = "已关联"
CORRECTION_STATES = [
    CORRECTION_PENDING,
    CORRECTION_ACCEPTED,
    CORRECTION_REJECTED,
    CORRECTION_DONE,
]

# 差异类型：来件在收件环节被订阅方退回
DIFF_RECIPIENT_RETURN = "收件时退回"
# 差异类型：回执中心做分发核验时驳回（版本/行数/资格不符）
DIFF_VERIFY_REJECT = "分发核验时驳回"

# 回执处理阶段
STAGE_PENDING = "待签收"
STAGE_VERIFIED = "已核销"
STAGE_REJECTED = "已驳回"
STAGE_RETURNED = "已退回"
STAGE_CORRECTING = "更正待受理"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DistReceiptService(BaseModuleService):
    MODULE = "dist_receipt"
    ENTITY = "回执记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = [
        "回执编号", "分发批次", "订阅方", "实际收件主体", "签收凭证号",
        "签收版本", "签收行数", "回执状态", "差异说明",
    ]
    REQUIRED_FIELDS = ["回执编号", "分发批次", "订阅方", "实际收件主体"]
    STATUS_ORDER = ["已回收", "部分回收", "未回收"]
    # 通用动作只做本件状态维护，不得再冲销分发任务
    ACTION_RULES = {"重发回执请求": "部分回收", "标记差异": "未回收"}
    NEGATIVE_ACTIONS = []

    # ------------------------------------------------------------------
    # 查询与权限
    # ------------------------------------------------------------------

    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        operator: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """列出来件；带 operator 时按权限收敛——订阅方只能查看自己的凭证。"""
        rows = list(store.rows(self.MODULE))
        if operator:
            rows = [row for row in rows if row.get("实际收件主体") == operator]
        for field, expected in (filters or {}).items():
            if field in self.LIST_FIELDS:
                rows = [
                    row for row in rows
                    if expected.casefold() in str(row.get(field, "")).casefold()
                ]
        if keyword:
            rows = [
                row for row in rows
                if keyword.casefold() in str(row.get("回执编号", "")).casefold()
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int, operator: str | None = None) -> dict[str, Any] | None:
        """来件详情按权限开放：非值班员只能查看本主体的来件。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        if operator and entry.get("实际收件主体") != operator:
            return None
        return entry

    def _find_dispatch_task(self, batch: str, recipient: str) -> dict[str, Any] | None:
        """联合键定位原发件：分发批次 + 实际收件主体，缺一不可。"""
        return next(
            (
                task for task in store.rows("dist_task")
                if task.get("分发批次") == batch and task.get("订阅方") == recipient
            ),
            None,
        )

    # ------------------------------------------------------------------
    # 签收核对（核心修复）
    # ------------------------------------------------------------------

    def submit_signoff(
        self,
        entry_id: int,
        operator: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """操作员在来件详情提交实际签收归属与签收凭证，服务端核验并返回核销凭据。

        核验顺序：
        1. 来件存在且操作员对该来件有签收资格（实际收件主体一致）；
        2. 相同签收凭证重复送达 → 查回原核销凭据，幂等返回；
        3. (分发批次, 实际收件主体) 联合定位原发件，资格不符直接驳回；
        4. 签收版本、签收行数与原发件核验，差异归本件，不影响他方发放。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "code": "not_found", "message": "来件不存在"}

        recipient = str(payload.get("实际收件主体") or entry.get("实际收件主体") or "").strip()
        voucher_no = str(payload.get("签收凭证号") or "").strip()
        version = str(payload.get("签收版本") or "").strip()
        row_count = payload.get("签收行数")
        note = str(payload.get("差异说明") or "").strip()

        # 1. 权限：只有本件实际收件主体能提交签收
        if entry.get("实际收件主体") != operator:
            return {
                "ok": False,
                "code": "forbidden",
                "message": f"{operator} 对来件 {entry.get('回执编号')} 无签收资格，"
                           f"该来件归属 {entry.get('实际收件主体')}",
            }
        if not recipient:
            return {"ok": False, "code": "bad_request", "message": "缺少实际签收归属"}

        # 2. 幂等：相同签收凭证重新送来 → 查回原件与原核销凭据
        if voucher_no:
            original = self._find_by_voucher(voucher_no)
            if original is not None and original.get("id") != entry_id:
                return {
                    "ok": True,
                    "code": "duplicate_voucher",
                    "message": f"签收凭证 {voucher_no} 已办理，查回原来件 "
                               f"{original.get('回执编号')} 的核销凭据，不重复核销",
                    "entry": original,
                    "writeoff_token": original.get("核销凭据号"),
                    "duplicate_of": original.get("id"),
                }
            if entry.get("处理阶段") == STAGE_VERIFIED and entry.get("签收凭证号") == voucher_no:
                return {
                    "ok": True,
                    "code": "already_writeoff",
                    "message": "该来件已核销，返回原核销凭据",
                    "entry": entry,
                    "writeoff_token": entry.get("核销凭据号"),
                }

        # 3. 联合键定位原发件（分发号 + 实际收件主体共同决定签收资格）
        task = self._find_dispatch_task(entry.get("分发批次", ""), recipient)
        if task is None:
            # 找不到属于该主体的原发件：本件驳回，不动任何分发任务
            self._reject_entry(
                entry,
                DIFF_VERIFY_REJECT,
                f"分发批次 {entry.get('分发批次')} 不属于收件主体 {recipient}，无签收资格",
            )
            return {
                "ok": False,
                "code": "not_eligible",
                "message": f"分发号 {entry.get('分发批次')} 与收件主体 {recipient} 不匹配，"
                           "签收资格核验驳回",
                "entry": entry,
            }

        # 4. 版本与行数核验（拿到正确的分发号还不够）
        expected_version = str(task.get("发件版本") or "").strip()
        expected_rows = task.get("发件行数")
        mismatches: list[str] = []
        if version and expected_version and version != expected_version:
            mismatches.append(f"签收版本 {version} ≠ 原发件版本 {expected_version}")
        if row_count not in (None, "") and expected_rows not in (None, ""):
            if int(row_count) != int(expected_rows):  # type: ignore[arg-type]
                mismatches.append(
                    f"签收行数 {row_count} ≠ 原发件行数 {expected_rows}"
                )

        if mismatches:
            reason = "；".join(mismatches)
            self._reject_entry(
                entry,
                DIFF_VERIFY_REJECT,
                f"分发核验驳回：{reason}",
                voucher_no=voucher_no,
                version=version,
                row_count=row_count,
            )
            # 差异归本件：B 报缺件不能把 A 的成功发放冲销，这里绝不改 task 状态
            return {
                "ok": False,
                "code": "verify_rejected",
                "message": f"差异归本件处理：{reason}",
                "entry": entry,
                "dispatch_task_id": task.get("id"),
            }

        # 5. 核验通过：服务端生成签收核销凭据并关联原发件
        token = entry.get("核销凭据号") or self._mint_token(entry, task)
        entry.update({
            "实际收件主体": recipient,
            "签收凭证号": voucher_no,
            "签收版本": version or expected_version,
            "签收行数": int(row_count) if row_count not in (None, "") else expected_rows,
            "核销凭据号": token,
            "关联分发任务": task.get("id"),
            "发件凭证号": task.get("发件凭证号", ""),
            "处理阶段": STAGE_VERIFIED,
            "差异类型": "",
            "差异说明": note or "签收版本与行数核验一致",
            "status": "已回收",
            "回执状态": "已回收",
            "pending": False,
            "abnormal": False,
            "核销时间": _now(),
        })
        return {
            "ok": True,
            "code": "writeoff",
            "message": "签收核对通过，已核发签收核销凭据",
            "entry": entry,
            "writeoff_token": token,
            "dispatch_task_id": task.get("id"),
            "dispatch_voucher": task.get("发件凭证号"),
        }

    def mark_recipient_return(self, entry_id: int, operator: str, reason: str) -> dict[str, Any]:
        """订阅方收件时直接退回来件（区别于回执中心核验驳回）。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "code": "not_found", "message": "来件不存在"}
        if entry.get("实际收件主体") != operator:
            return {"ok": False, "code": "forbidden", "message": "只能退回本主体的来件"}
        entry["处理阶段"] = STAGE_RETURNED
        entry["差异类型"] = DIFF_RECIPIENT_RETURN
        entry["差异说明"] = f"收件时退回：{reason}"
        entry["status"] = "未回收"
        entry["回执状态"] = "未回收"
        entry["abnormal"] = True
        entry["退回时间"] = _now()
        return {"ok": True, "message": "已登记为收件时退回，差异归本件处理", "entry": entry}

    # ------------------------------------------------------------------
    # 更正单：误填原件 → 本主体提交更正 → 值班员受理
    # ------------------------------------------------------------------

    def submit_correction(
        self,
        entry_id: int,
        operator: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """订阅方从来件详情，以错填原件为依据提交更正。

        已经办理过更正的差异不再更正第二次（幂等保护）。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "code": "not_found", "message": "来件不存在"}
        if entry.get("实际收件主体") != operator:
            return {"ok": False, "code": "forbidden", "message": "只能对本主体的来件提交更正"}

        existing = self._correction_for_entry(entry_id)
        if existing is not None:
            # 已办理的差异不再更正第二次；待补交时允许补交凭证（走 resubmit）
            if existing.get("更正状态") in (CORRECTION_PENDING, CORRECTION_ACCEPTED,
                                             CORRECTION_DONE):
                return {
                    "ok": False,
                    "code": "correction_exists",
                    "message": f"该来件差异已办理（{existing.get('更正状态')}），不再二次更正",
                    "correction": existing,
                }

        table = store.rows("receipt_correction")
        correction = {
            "id": max((int(row.get("id", 0)) for row in table), default=0) + 1,
            "更正单号": f"CR-{entry_id}-{max((int(row.get('id', 0)) for row in table), default=0) + 1}",
            "来件id": entry_id,
            "回执编号": entry.get("回执编号"),
            "分发批次": entry.get("分发批次"),
            "申请主体": operator,
            "关联分发任务": payload.get("关联分发任务", entry.get("关联分发任务")),
            "原签收凭证号": payload.get("原签收凭证号", entry.get("签收凭证号", "")),
            "更正凭证号": str(payload.get("更正凭证号") or "").strip(),
            "更正说明": str(payload.get("更正说明") or "").strip(),
            "更正状态": CORRECTION_PENDING,
            "status": CORRECTION_PENDING,
            "pending": True,
            "abnormal": False,
            "提交时间": _now(),
            "受理时间": "",
        }
        table.append(correction)
        entry["处理阶段"] = STAGE_CORRECTING
        return {
            "ok": True,
            "code": "correction_submitted",
            "message": "更正已提交，等待值班员受理",
            "correction": correction,
        }

    def review_correction(self, correction_id: int, decision: str, note: str = "") -> dict[str, Any]:
        """值班员受理更正：受理 / 驳回要求补交凭证。

        受理语义：错填原件的差异归本件办结（B 永远不能核销 A 的 X），
        更正单关联到申请主体自己的分发任务（如 B 的 Y）；若该任务已有
        本主体的已核销回执，则联动结算。已办理的差异不再更正第二次。
        """
        correction = store.find("receipt_correction", correction_id)
        if correction is None:
            return {"ok": False, "code": "not_found", "message": "更正单不存在"}
        if correction.get("更正状态") in (CORRECTION_ACCEPTED, CORRECTION_DONE):
            return {
                "ok": False,
                "code": "already_handled",
                "message": "该差异已办理，不再更正第二次",
                "correction": correction,
            }

        entry = store.find(self.MODULE, int(correction.get("来件id", 0)))
        if entry is None:
            return {"ok": False, "code": "not_found", "message": "关联来件不存在"}

        if decision == "reject":
            correction["更正状态"] = CORRECTION_REJECTED
            correction["status"] = CORRECTION_REJECTED
            correction["abnormal"] = True
            correction["受理说明"] = note or "凭证不足，需补交凭证"
            correction["受理时间"] = _now()
            return {
                "ok": True,
                "code": "need_material",
                "message": "已驳回，需要申请主体补交凭证",
                "correction": correction,
            }

        if decision != "accept":
            return {"ok": False, "code": "bad_request", "message": "decision 仅支持 accept/reject"}

        if not correction.get("更正凭证号"):
            correction["更正状态"] = CORRECTION_REJECTED
            correction["status"] = CORRECTION_REJECTED
            correction["abnormal"] = True
            correction["受理说明"] = "缺少更正凭证号，需补交凭证"
            correction["受理时间"] = _now()
            return {"ok": True, "code": "need_material",
                    "message": "更正凭证缺失，需要申请主体补交凭证", "correction": correction}

        # 受理：差异归本件办结。错填原件不产生 X 的核销凭据（X 只由 A 核销）。
        entry["处理阶段"] = "更正已办结"
        entry["差异说明"] = f"更正受理，差异归本件办结：{correction.get('更正说明') or note}"
        entry["abnormal"] = False
        entry["pending"] = False
        entry["核销凭据号"] = entry.get("核销凭据号") or ""
        correction["受理说明"] = note or "更正凭证核验通过，差异归本件办结"
        correction["受理时间"] = _now()
        correction["pending"] = False

        # 关联到申请主体自己的分发任务（如 B 的 Y），并尝试联动结算
        linked_task_id = correction.get("关联分发任务")
        settle: dict[str, Any] = {}
        if linked_task_id:
            task = store.find("dist_task", int(linked_task_id))
            if task is not None and task.get("订阅方") == correction.get("申请主体"):
                from app.services.dist_task import DistTaskService
                settle = DistTaskService().settle_by_receipt(int(linked_task_id))
                correction["关联发件凭证号"] = task.get("发件凭证号")
                if settle.get("ok"):
                    correction["更正状态"] = CORRECTION_DONE
                    correction["status"] = CORRECTION_DONE
                    correction["核销凭据号"] = settle.get("writeoff_token")
                else:
                    # 已关联到 Y，但 Y 尚缺本主体已核销回执，等 B 完成 Y 签收后再结算
                    correction["更正状态"] = CORRECTION_ACCEPTED
                    correction["status"] = CORRECTION_ACCEPTED
            else:
                return {"ok": False, "code": "not_eligible",
                        "message": "关联分发任务不属于申请主体，拒绝关联",
                        "correction": correction}
        else:
            correction["更正状态"] = CORRECTION_ACCEPTED
            correction["status"] = CORRECTION_ACCEPTED

        return {
            "ok": True,
            "code": "correction_accepted",
            "message": "更正已受理，差异归本件办结",
            "correction": correction,
            "settle": settle,
        }

    def resubmit_correction(self, correction_id: int, operator: str, payload: dict[str, Any]) -> dict[str, Any]:
        """被要求补交凭证后，申请主体补交更正凭证，重新进入待受理。"""
        correction = store.find("receipt_correction", correction_id)
        if correction is None:
            return {"ok": False, "code": "not_found", "message": "更正单不存在"}
        if correction.get("申请主体") != operator:
            return {"ok": False, "code": "forbidden", "message": "只能补交本主体的更正单"}
        if correction.get("更正状态") != CORRECTION_REJECTED:
            return {"ok": False, "code": "state_conflict",
                    "message": "仅「需补交凭证」状态可补交，已办理差异不再更正"}
        voucher = str(payload.get("更正凭证号") or "").strip()
        if not voucher:
            return {"ok": False, "code": "bad_request", "message": "补交凭证号不能为空"}
        correction["更正凭证号"] = voucher
        if payload.get("更正说明"):
            correction["更正说明"] = str(payload.get("更正说明"))
        correction["更正状态"] = CORRECTION_PENDING
        correction["status"] = CORRECTION_PENDING
        correction["pending"] = True
        correction["abnormal"] = False
        correction["提交时间"] = _now()
        return {"ok": True, "code": "resubmitted", "message": "凭证已补交，等待受理",
                "correction": correction}

    def list_corrections(self, operator: str | None = None) -> list[dict[str, Any]]:
        """更正队列；订阅方只看本主体，值班员看全部。"""
        rows = store.rows("receipt_correction")
        if operator:
            rows = [row for row in rows if row.get("申请主体") == operator]
        return rows

    def correction_status(self, entry_id: int) -> dict[str, Any] | None:
        """值班员处理后续来件时核对：更正仍待受理 / 已关联 / 需补交。"""
        return self._correction_for_entry(entry_id)

    # ------------------------------------------------------------------
    # 兼容旧接口的方法（修复为联合键 + 不冲销他方）
    # ------------------------------------------------------------------

    def verify_receipt(self, entry_id: int) -> dict[str, Any]:
        """旧入口保留：按 (分发批次, 实际收件主体) 联合核对版本与行数。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "回执记录不存在"}
        task = self._find_dispatch_task(
            entry.get("分发批次", ""), entry.get("实际收件主体", entry.get("订阅方", ""))
        )
        if task is None:
            entry["status"] = "未回收"
            entry["差异说明"] = "分发批次与收件主体联合匹配不到原发件"
            return {"ok": False, "message": "联合键匹配不到属于该主体的分发批次"}
        if task.get("status") == "已送达":
            entry["status"] = "已回收"
            entry["pending"] = False
            return {"ok": True, "message": "回执与分发结果一致"}
        entry["status"] = "部分回收"
        entry["差异说明"] = f"分发状态为 {task.get('status')}"
        return {"ok": False, "message": "回执与分发结果不一致"}

    def mark_diff(self, entry_id: int, diff: str, operator: str | None = None) -> str:
        """标记差异：差异归本件，只更新本回执，不再把任何分发任务冲销为失败。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return "回执记录不存在"
        entry["status"] = "未回收"
        entry["差异说明"] = diff
        entry["abnormal"] = True
        entry["差异类型"] = entry.get("差异类型") or DIFF_VERIFY_REJECT
        return f"差异已标记并归本件处理: {diff}（不影响其他订阅方的分发任务）"

    def resend_request(self, entry_id: int) -> dict[str, Any]:
        """重发回执请求并等待订阅方回传。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "回执记录不存在"}
        entry["status"] = "部分回收"
        entry["pending"] = True
        entry["重发时间"] = _now()
        return {"ok": True, "message": "回执请求已重发"}

    def consume_dist_results(self, entry_id: int) -> list[dict[str, Any]]:
        """读取本主体的送达批次作为核对输入（按收件主体过滤）。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return []
        subscriber = entry.get("实际收件主体") or entry.get("订阅方", "")
        return [
            task for task in store.rows("dist_task")
            if task.get("订阅方") == subscriber and task.get("status") in ("已送达", "分发失败")
        ]

    def stats_by_subscriber(self) -> dict[str, dict[str, int]]:
        """按实际收件主体统计回执回收情况。"""
        stats: dict[str, dict[str, int]] = {}
        for row in store.rows(self.MODULE):
            subscriber = row.get("实际收件主体") or row.get("订阅方", "未知")
            bucket = stats.setdefault(
                subscriber, {"已回收": 0, "部分回收": 0, "未回收": 0}
            )
            status = row.get("status", "未回收")
            if status in bucket:
                bucket[status] += 1
        return stats

    def notify_receipt_gap(self, entry_id: int) -> str:
        """把回执缺口通知订阅方重新上传。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return "回执记录不存在"
        subscriber = entry.get("实际收件主体") or entry.get("订阅方", "")
        for sub in store.rows("subscriber_mgr"):
            if sub.get("订阅方标识") == subscriber:
                sub["pending"] = True
        return f"已通知 {subscriber} 补传回执"

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _find_by_voucher(self, voucher_no: str) -> dict[str, Any] | None:
        """相同签收凭证查回原件。"""
        if not voucher_no:
            return None
        return next(
            (row for row in store.rows(self.MODULE)
             if row.get("签收凭证号") == voucher_no),
            None,
        )

    def _correction_for_entry(self, entry_id: int) -> dict[str, Any] | None:
        return next(
            (row for row in store.rows("receipt_correction")
             if int(row.get("来件id", 0)) == entry_id),
            None,
        )

    def _mint_token(self, entry: dict[str, Any], task: dict[str, Any]) -> str:
        """服务端生成签收核销凭据号。"""
        seq = sum(1 for row in store.rows(self.MODULE) if row.get("核销凭据号")) + 1
        return f"WO-{entry.get('分发批次', 'B')}-{task.get('id')}-{seq:03d}"

    def _reject_entry(
        self,
        entry: dict[str, Any],
        diff_type: str,
        reason: str,
        *,
        voucher_no: str = "",
        version: str = "",
        row_count: Any = None,
    ) -> None:
        """驳回本件：差异归本件，绝不触碰分发任务。"""
        entry["处理阶段"] = STAGE_REJECTED
        entry["差异类型"] = diff_type
        entry["差异说明"] = reason
        entry["status"] = "未回收"
        entry["回执状态"] = "未回收"
        entry["abnormal"] = True
        entry["pending"] = True
        if voucher_no:
            entry["签收凭证号"] = voucher_no
        if version:
            entry["签收版本"] = version
        if row_count not in (None, ""):
            entry["签收行数"] = row_count
        entry["核销凭据号"] = ""
        entry["核销时间"] = _now()
