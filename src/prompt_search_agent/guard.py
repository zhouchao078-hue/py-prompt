"""公网安全层：访问口令、IP 限流、全局日配额、会话签名与 trace_id。

设计取舍（都是为 demo 场景服务，写在注释里便于后续演进）：

* 限流与配额是**单进程内存态**，因此部署必须保持 ``--workers 1``。
  要横向扩容就把 ``DemoGuard`` 换成 Redis 实现。
* 口令走 ``Authorization: Bearer``，不用 cookie —— 无 CSRF 面，也不需要会话存储。
* 会话签名用 HMAC，服务端无状态，thread_id 泄露但没签名也无法读取历史。
"""

import hashlib
import hmac
import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from prompt_search_agent.config import Settings

LOGGER = logging.getLogger(__name__)

RATE_WINDOW_SECONDS = 3600.0
TRACKED_IPS_LIMIT = 4096
EXEMPT_PATHS = frozenset(
    {"/", "/api/health", "/api/version", "/metrics", "/favicon.svg"}
)
EXEMPT_PREFIXES = ("/static/",)

TRACE_HEADER = "x-request-id"


class DemoGuard:
    """口令校验 + 每 IP 滑动窗口 + 全局日配额。"""

    def __init__(
        self,
        access_code: str,
        per_ip_limit: int,
        daily_cap: int,
    ) -> None:
        self.access_code = access_code
        self.per_ip_limit = per_ip_limit
        self.daily_cap = daily_cap
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._day = ""
        self._day_count = 0

    @staticmethod
    def client_ip(request: Request) -> str:
        """取真实客户端 IP。

        必须取**最右**一项：反代是追加写入的，最左那格是客户端自己填的，
        取它等于让攻击者每次换一个假 IP 绕过限流。
        """
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [item.strip() for item in forwarded.split(",") if item.strip()]

        if parts:
            return parts[-1]

        return request.client.host if request.client else "unknown"

    def _check_daily_quota(self, now_label: str) -> Response | None:
        if now_label != self._day:
            self._day, self._day_count = now_label, 0

        if self._day_count >= self.daily_cap:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "quota_exhausted",
                    "message": "今日演示额度已用完，明天再来。",
                },
            )

        return None

    def _check_rate_limit(self, ip: str, now: float) -> Response | None:
        if len(self._hits) > TRACKED_IPS_LIMIT:
            self._sweep(now)

        hits = self._hits[ip]

        while hits and now - hits[0] > RATE_WINDOW_SECONDS:
            hits.popleft()

        if len(hits) >= self.per_ip_limit:
            return JSONResponse(
                status_code=429,
                content={
                    "code": "rate_limited",
                    "message": "请求太频繁了，歇一会儿再试。",
                },
            )

        return None

    def _sweep(self, now: float) -> None:
        """被扫段时 IP 表会无限膨胀，定期清掉过期条目。"""
        stale = [
            ip
            for ip, hits in self._hits.items()
            if not hits or now - hits[-1] > RATE_WINDOW_SECONDS
        ]

        for ip in stale:
            del self._hits[ip]

    def check(self, request: Request, trace_id: str) -> Response | None:
        """返回 None 表示放行，否则返回拒绝响应。"""
        path = request.url.path

        if path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES):
            return None

        now = time.monotonic()

        rejection = self._check_daily_quota(time.strftime("%Y-%m-%d"))

        if rejection is not None:
            self._log_rejection(request, trace_id, rejection, "配额耗尽")
            return rejection

        ip = self.client_ip(request)
        rejection = self._check_rate_limit(ip, now)

        if rejection is not None:
            self._log_rejection(request, trace_id, rejection, f"限流 {ip}")
            return rejection

        token = request.headers.get("authorization", "")
        token = token.removeprefix("Bearer ").strip()

        if not hmac.compare_digest(token, self.access_code):
            response = JSONResponse(
                status_code=401,
                content={
                    "code": "unauthorized",
                    "message": "需要访问口令。",
                },
            )
            self._log_rejection(request, trace_id, response, f"口令错误 {ip}")
            return response

        self._hits[ip].append(now)
        self._day_count += 1
        return None

    @staticmethod
    def _log_rejection(
        request: Request,
        trace_id: str,
        response: Response,
        reason: str,
    ) -> None:
        LOGGER.info(
            "security reject trace_id=%s status=%s path=%s reason=%s",
            trace_id,
            response.status_code,
            request.url.path,
            reason,
        )


def sign_token(value: str, secret: str) -> str:
    """给任意标识签名；会话 cookie 用它防篡改。"""
    digest = hmac.new(
        secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    )
    return digest.hexdigest()[:32]


def verify_token(value: str, token: str, secret: str) -> bool:
    if not token:
        return False

    return hmac.compare_digest(sign_token(value, secret), token)


def install_security(app: FastAPI, settings: Settings | None) -> None:
    """安装 trace_id + 口令/限流/配额中间件。

    trace 必须包裹在限流之外，否则被拒绝的请求查不到 trace。
    未配置口令时只装 trace，方便本机开发。
    """
    guard: DemoGuard | None = None
    max_body_bytes = settings.max_request_body_bytes if settings else 0

    if settings is not None and settings.is_public_mode:
        access_code = settings.demo_access_code

        if access_code is not None:
            guard = DemoGuard(
                access_code.get_secret_value(),
                settings.rate_limit_per_ip_per_hour,
                settings.daily_request_cap,
            )

    @app.middleware("http")
    async def security_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        trace_id = request.headers.get(TRACE_HEADER) or uuid4().hex[:16]
        request.state.trace_id = trace_id

        # 请求体上限：uvicorn 默认不限，1GB 的 body 会先整块读进内存。
        declared = request.headers.get("content-length", "")

        if (
            max_body_bytes
            and declared.isdigit()
            and int(declared) > max_body_bytes
        ):
            rejection = JSONResponse(
                status_code=413,
                content={
                    "code": "payload_too_large",
                    "message": "请求体过大。",
                },
            )
            rejection.headers[TRACE_HEADER] = trace_id
            return rejection

        if guard is not None:
            rejection = guard.check(request, trace_id)

            if rejection is not None:
                rejection.headers[TRACE_HEADER] = trace_id
                return rejection

        response = await call_next(request)
        response.headers[TRACE_HEADER] = trace_id
        return response
