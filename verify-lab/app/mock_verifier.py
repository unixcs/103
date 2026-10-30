"""本地模拟的"审核网关" —— 对照原项目 */sheerid_verifier.py

原项目：直接打 SheerID 的私有 REST 接口（collectStudentPersonalInfo →
docUpload → S3 预签名 PUT → completeDocUpload），提交伪造证件。

这里换成一个纯本地的状态机，不联网、不上传、不校验任何真实身份：
它只演示"多步状态机 + 外部资源上传 + 结果轮询"这个结构本身怎么写。
所有接口名、字段名都是自定义的，和 SheerID 无关。
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_STEPS = ("collectApplicantInfo", "uploadDocument", "complete", "review", "success")


class GatewayError(Exception):
    """业务错误：调用方应该把错误展示给用户（并退积分）。"""


@dataclass
class Verification:
    verification_id: str
    user_id: int
    current_step: str = "collectApplicantInfo"
    applicant: dict = field(default_factory=dict)
    document_path: Optional[Path] = None
    reward_code: Optional[str] = None
    errors: list[str] = field(default_factory=list)


class MockReviewGateway:
    """模拟第三方审核服务。审核规则是完全确定的：资料齐全 + 有文档 = 通过。"""

    def __init__(self, evidence_dir: str | Path = "outputs/evidence"):
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._ids = itertools.count(1)
        self._db: dict[str, Verification] = {}

    # 1) 创建审核单
    def create(self, user_id: int) -> str:
        vid = f"LAB{next(self._ids):06d}"
        self._db[vid] = Verification(vid, user_id)
        return vid

    # 2) 提交申请信息
    def collect_applicant_info(self, vid: str, **fields) -> str:
        v = self._get(vid)
        if v.current_step != "collectApplicantInfo":
            raise GatewayError(f"步骤错误：当前是 {v.current_step}")
        required = ("full_name", "course")
        missing = [k for k in required if not fields.get(k)]
        if missing:
            v.errors.extend(f"缺少字段 {k}" for k in missing)
            v.current_step = "error"
            raise GatewayError(f"缺少字段：{', '.join(missing)}")
        v.applicant = fields
        v.current_step = "uploadDocument"
        return v.current_step

    # 3) 申请上传地址（真实场景是 S3 预签名 URL，这里就是本地文件路径）
    def request_upload(self, vid: str, file_name: str, size: int) -> dict:
        v = self._get(vid)
        if v.current_step != "uploadDocument":
            raise GatewayError(f"步骤错误：当前是 {v.current_step}")
        if size <= 0 or size > 2 * 1024 * 1024:
            raise GatewayError("文件大小必须在 0~2MB 之间")
        upload_url = self.evidence_dir / f"{vid}-{file_name}"
        return {"uploadUrl": str(upload_url), "method": "PUT"}

    # 4) 真正"上传"（本地就是复制文件）
    def put_object(self, upload_url: str, data: bytes) -> None:
        Path(upload_url).write_bytes(data)

    # 5) 提交完成
    def complete_upload(self, vid: str) -> str:
        v = self._get(vid)
        if v.current_step != "uploadDocument":
            raise GatewayError(f"步骤错误：当前是 {v.current_step}")
        v.document_path = next(iter(self.evidence_dir.glob(f"{vid}-*.png")), None)
        if v.document_path is None:
            raise GatewayError("没有找到已上传的文档")
        v.current_step = "review"
        return v.current_step

    # 6) 轮询结果（原项目这里不轮询，直接把"等审核"甩给用户）
    def poll(self, vid: str, timeout: float = 5.0, interval: float = 0.3) -> dict:
        v = self._get(vid)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if v.current_step == "success":
                return {"status": "success", "rewardCode": v.reward_code}
            if v.current_step == "error":
                return {"status": "error", "errors": v.errors}
            time.sleep(interval)
            self._review(v)                 # 模拟人工审核
        return {"status": "pending", "currentStep": v.current_step}

    def _review(self, v: Verification) -> None:
        if v.current_step == "review":
            v.current_step = "success"
            v.reward_code = f"REWARD-{v.verification_id}"

    def _get(self, vid: str) -> Verification:
        if vid not in self._db:
            raise GatewayError(f"审核单不存在：{vid}")
        return self._db[vid]
