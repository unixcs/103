"""按业务类型分桶的信号量 —— 对照原项目 utils/concurrency.py

原项目的三个问题，这里各修一处：
1. adjust_concurrency_limits() 直接 new Semaphore() 替换字典，
   正在等旧信号量的任务不受影响 —— 这里改成只允许初始化一次，禁止热替换；
2. get_concurrency_stats() 报的 limit 是 //3，实际创建是 //5 —— 这里 limit 由同一个值算；
3. start_load_monitoring() 从未被调用（死代码）—— 这里不写死代码，
   需要动态调整时由调用方显式 await adjust()。
"""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


def _base_limit() -> int:
    """按 CPU 数量估算总并发，环境变量可覆盖（便于测试）。"""
    if "VERIFY_LAB_CONCURRENCY" in os.environ:
        return max(1, int(os.environ["VERIFY_LAB_CONCURRENCY"]))
    return max(2, min((os.cpu_count() or 4) * 2, 32))


class SemaphoreRegistry:
    def __init__(self, base: int | None = None, per_type_divisor: int = 4):
        self.base = base or _base_limit()
        self.divisor = per_type_divisor
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    @property
    def per_type_limit(self) -> int:
        return max(1, self.base // self.divisor)

    def get(self, kind: str) -> asyncio.Semaphore:
        """同一种业务共用一个信号量，不同业务互不阻塞。"""
        if kind not in self._semaphores:
            self._semaphores[kind] = asyncio.Semaphore(self.per_type_limit)
            logger.info("为 %s 创建信号量 limit=%d", kind, self.per_type_limit)
        return self._semaphores[kind]

    def stats(self) -> dict[str, dict[str, int]]:
        report = {}
        for kind, sem in self._semaphores.items():
            available = sem._value          # 内部属性，仅用于观测
            report[kind] = {
                "limit": self.per_type_limit,
                "in_use": self.per_type_limit - available,
                "available": available,
            }
        return report


registry = SemaphoreRegistry()
