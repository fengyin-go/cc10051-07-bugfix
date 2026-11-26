"""签收核对场景种子数据。

覆盖题目叙述的完整局面：
- 订阅方 A、B 均为生效订阅方；
- 分发批次 D-X 归 A（发件版本 v12、8 条），D-Y 归 B（发件版本 v7、5 条）；
- A 已正确签收 X（已核销凭据），B 持同号差异迟到（版本/行数不符，驳回）；
- A 的补签凭证单独成为一件来件；B 错填 X 的原件作为其提交更正的依据；
- B 另有已发出的 Y，附可单独复核的 Y 交付凭证。

通用样例数据保持不动，本文件只追加叙事行与 receipt_correction 新表。
"""
from __future__ import annotations

from typing import Any

# 订阅方（A、B）
SCENARIO_SUBSCRIBERS: list[dict[str, Any]] = [
    {
        "id": 901,
        "status": "已生效",
        "pending": False,
        "abnormal": False,
        "订阅方标识": "订阅方A",
        "订阅实体": "客户主数据",
        "分发格式": "JSON",
        "订阅过滤": "区域=华东",
        "生效状态": "已生效",
    },
    {
        "id": 902,
        "status": "已生效",
        "pending": False,
        "abnormal": False,
        "订阅方标识": "订阅方B",
        "订阅实体": "客户主数据",
        "分发格式": "JSON",
        "订阅过滤": "区域=华北",
        "生效状态": "已生效",
    },
]

# 分发任务：X 归 A，Y 归 B；联合键 (分发批次, 订阅方)
SCENARIO_DIST_TASKS: list[dict[str, Any]] = [
    {
        "id": 910,
        "status": "已送达",
        "pending": False,
        "abnormal": False,
        "分发批次": "D-X",
        "订阅方": "订阅方A",
        "记录范围": "版本 v12",
        "发件版本": "v12",
        "发件行数": 8,
        "发件凭证号": "DV-D-X-910",
        "分发状态": "已送达",
        "回执状态": "已回收",
        "核销凭据号": "WO-D-X-910-001",
        "关联回执编号": "RC-X-A",
        "实际签收行数": 8,
    },
    {
        "id": 911,
        "status": "已送达",
        "pending": True,
        "abnormal": False,
        "分发批次": "D-Y",
        "订阅方": "订阅方B",
        "记录范围": "版本 v7",
        "发件版本": "v7",
        "发件行数": 5,
        "发件凭证号": "DV-D-Y-911",
        "分发状态": "已送达",
        "回执状态": "待签收",
        "核销凭据号": "",
        "关联回执编号": "",
        "实际签收行数": None,
    },
]

# 回执来件
SCENARIO_RECEIPTS: list[dict[str, Any]] = [
    # 1) A 正确签收 X：版本 v12、8 条，已核销
    {
        "id": 920,
        "status": "已回收",
        "pending": False,
        "abnormal": False,
        "回执编号": "RC-X-A",
        "分发批次": "D-X",
        "订阅方": "订阅方A",
        "实际收件主体": "订阅方A",
        "签收凭证号": "SIG-X-A-1",
        "签收版本": "v12",
        "签收行数": 8,
        "核销凭据号": "WO-D-X-910-001",
        "关联分发任务": 910,
        "发件凭证号": "DV-D-X-910",
        "处理阶段": "已核销",
        "差异类型": "",
        "回执状态": "已回收",
        "差异说明": "签收版本与行数核验一致",
    },
    # 2) B 拿同号 D-X 报来的差异（迟到）：版本/行数都不符，分发核验驳回；差异归本件
    {
        "id": 921,
        "status": "未回收",
        "pending": True,
        "abnormal": True,
        "回执编号": "RC-X-B-DIFF",
        "分发批次": "D-X",
        "订阅方": "订阅方B",
        "实际收件主体": "订阅方B",
        "签收凭证号": "SIG-X-B-WRONG",
        "签收版本": "v11",
        "签收行数": 6,
        "核销凭据号": "",
        "关联分发任务": None,
        "发件凭证号": "",
        "处理阶段": "已驳回",
        "差异类型": "分发核验时驳回",
        "回执状态": "未回收",
        "差异说明": "分发核验驳回：签收版本 v11 ≠ 原发件版本 v12；签收行数 6 ≠ 原发件行数 8",
    },
    # 3) A 的补签凭证来件：同属 A 的 D-X，待 A 提交（重复凭证将幂等查回原件）
    {
        "id": 922,
        "status": "未回收",
        "pending": True,
        "abnormal": False,
        "回执编号": "RC-X-A-RESIGN",
        "分发批次": "D-X",
        "订阅方": "订阅方A",
        "实际收件主体": "订阅方A",
        "签收凭证号": "",
        "签收版本": "",
        "签收行数": None,
        "核销凭据号": "",
        "关联分发任务": 910,
        "发件凭证号": "DV-D-X-910",
        "处理阶段": "待签收",
        "差异类型": "",
        "回执状态": "未回收",
        "差异说明": "A 的补签凭证来件，待提交实际签收归属",
    },
    # 4) B 错填 X 的原件：B 收件时退回，作为 B 从自己来件详情提交更正的依据
    {
        "id": 923,
        "status": "未回收",
        "pending": True,
        "abnormal": True,
        "回执编号": "RC-X-B-RETURN",
        "分发批次": "D-X",
        "订阅方": "订阅方B",
        "实际收件主体": "订阅方B",
        "签收凭证号": "",
        "签收版本": "",
        "签收行数": None,
        "核销凭据号": "",
        "关联分发任务": None,
        "发件凭证号": "",
        "处理阶段": "已退回",
        "差异类型": "收件时退回",
        "回执状态": "未回收",
        "差异说明": "B 收件时退回：错填为 X 的原件，实际不属 B 的批次",
    },
    # 5) B 自己的 Y 来件：附可单独复核的 Y 交付凭证，待 B 签收
    {
        "id": 924,
        "status": "未回收",
        "pending": True,
        "abnormal": False,
        "回执编号": "RC-Y-B",
        "分发批次": "D-Y",
        "订阅方": "订阅方B",
        "实际收件主体": "订阅方B",
        "签收凭证号": "",
        "签收版本": "",
        "签收行数": None,
        "核销凭据号": "",
        "关联分发任务": 911,
        "发件凭证号": "DV-D-Y-911",
        "处理阶段": "待签收",
        "差异类型": "",
        "回执状态": "未回收",
        "差异说明": "B 的 Y 交付凭证来件，可单独复核",
    },
]

# 更正单：B 对错填 X 的原件（来件 923）提交的更正，初始待受理
SCENARIO_CORRECTIONS: list[dict[str, Any]] = [
    {
        "id": 930,
        "更正单号": "CR-923-1",
        "来件id": 923,
        "回执编号": "RC-X-B-RETURN",
        "分发批次": "D-X",
        "申请主体": "订阅方B",
        "关联分发任务": 911,
        "原签收凭证号": "",
        "更正凭证号": "CRV-B-X-FIX-1",
        "更正说明": "X 系错填，申请把差异归本件并更正到 B 自己的来件口径",
        "更正状态": "待受理",
        "status": "待受理",
        "pending": True,
        "abnormal": False,
        "提交时间": "2026-11-26T08:00:00+00:00",
        "受理时间": "",
    },
]


def seed_scenario(tables: dict[str, list[dict[str, Any]]]) -> None:
    """把场景行追加到内存表；新表缺省时创建。"""
    appends = {
        "subscriber_mgr": SCENARIO_SUBSCRIBERS,
        "dist_task": SCENARIO_DIST_TASKS,
        "dist_receipt": SCENARIO_RECEIPTS,
        "receipt_correction": SCENARIO_CORRECTIONS,
    }
    for module, rows in appends.items():
        tables.setdefault(module, [])
        existing_ids = {int(row.get("id", 0)) for row in tables[module]}
        for row in rows:
            if int(row.get("id", 0)) not in existing_ids:
                tables[module].append(dict(row))
