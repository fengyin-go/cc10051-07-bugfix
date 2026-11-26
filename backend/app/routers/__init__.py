"""业务路由汇总：回执中心专用路由先注册（路径更具体），再挂通用资源路由。"""
from __future__ import annotations

from app.routers import dist_receipt, resource

ROUTERS = [dist_receipt, resource]
