"""Request rate limiting.

WHY IN-PROCESS, AND WHAT THAT COSTS
===================================

Counters live in this process's memory. There is no Redis, because ANCHOR deploys
as a single instance and adding a second service to hold six integers would be
infrastructure for its own sake. The honest consequences, both documented in the
README:

* limits are **per instance**. Two replicas allow twice the traffic.
* limits **reset on restart**, so a deploy clears them.

Neither matters for what this actually defends against: a runaway client loop or a
stuck retry burning a Gemini quota. It is not a defence against a distributed
attacker, and it is not presented as one.

BUCKETS
=======

Endpoints are not equal, so one global limit would have to be set for the most
expensive route and would then cripple ordinary navigation:

    read    240/min   listing courses, opening a tab, polling a document's status
    write    60/min   creating a course, submitting an answer — a row, not a call
    ai       10/min and 60/hour   anything that reaches a model
    auth     10/min and 60/hour   login and registration, keyed by IP

The `ai` bucket is the one that protects the bill, and it is the reason the split
exists at all.

KEYING
======

By user id when a token is present, by client IP otherwise. Keying AI limits by
user is what makes them meaningful: several students behind one university NAT
must not share a quota, while one student cannot escape theirs by changing network.
Credential endpoints are keyed by IP precisely because there is no trusted user yet.
"""

# NOTE: deliberately no `from __future__ import annotations`. FastAPI resolves a
# dependency's signature at import time; with postponed annotations the `Request`
# parameter on RateLimit.__call__ arrives as the string "Request", which FastAPI
# cannot resolve and silently treats as a required QUERY parameter — every guarded
# route then 422s. Python 3.13 evaluates these annotations fine without it.
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Request, status

from app.core.config import settings
from app.core.exceptions import AnchorError


class RateLimitExceededError(AnchorError):
    """Too many requests. Carries the seconds until the window frees up."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS

    def __init__(self, message: str, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__(message)


@dataclass(frozen=True)
class Limit:
    """`count` requests per `window_seconds`."""

    count: int
    window_seconds: int


class SlidingWindowLimiter:
    """A sliding-window log, guarded by a lock.

    A fixed window would let a client send its whole allowance at 11:59:59 and the
    whole of the next at 12:00:00 — double the intended rate across two seconds,
    which for the AI bucket is exactly the burst worth preventing. Keeping the
    timestamps costs a deque of at most `count` floats per key.

    Uvicorn's default worker runs the event loop in one thread but dispatches sync
    endpoints to a threadpool, so the lock is not optional.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_prune = 0.0

    def check(self, key: str, limits: tuple[Limit, ...]) -> None:
        """Record one request against `key`, or raise if it does not fit.

        Nothing is recorded when the request is rejected: a client hammering a
        closed window would otherwise keep pushing its own reset further away.
        """
        if not limits:
            return

        now = time.monotonic()
        widest = max(limit.window_seconds for limit in limits)

        with self._lock:
            self._maybe_prune(now)
            hits = self._hits[key]

            while hits and now - hits[0] > widest:
                hits.popleft()

            for limit in limits:
                cutoff = now - limit.window_seconds
                used = sum(1 for hit in hits if hit > cutoff)
                if used >= limit.count:
                    oldest = next(hit for hit in hits if hit > cutoff)
                    retry_after = int(limit.window_seconds - (now - oldest)) + 1
                    raise RateLimitExceededError(
                        _message_for(limit, retry_after), retry_after
                    )

            hits.append(now)

    def _maybe_prune(self, now: float) -> None:
        """Drop keys with no recent activity, so memory tracks active clients.

        Called under the lock, at most once a minute — an unbounded dict keyed by
        IP is a slow memory leak on a long-running process.
        """
        if now - self._last_prune < 60.0:
            return
        self._last_prune = now
        stale = [
            key for key, hits in self._hits.items() if not hits or now - hits[-1] > 3600.0
        ]
        for key in stale:
            del self._hits[key]

    def reset(self) -> None:
        """Clear every counter. For tests, which must not inherit each other's."""
        with self._lock:
            self._hits.clear()
            self._last_prune = 0.0


def _message_for(limit: Limit, retry_after: int) -> str:
    unit = "minute" if limit.window_seconds <= 60 else "hour"
    return (
        f"Too many requests — the limit is {limit.count} per {unit}. "
        f"Try again in {retry_after} second{'s' if retry_after != 1 else ''}."
    )


limiter = SlidingWindowLimiter()


def _client_key(request: Request, bucket: str) -> str:
    """Identify the caller: user id if signed in, client IP otherwise.

    The bearer token is read but never decoded here — its *presence* and value are
    only used to build an opaque key. That keeps this module out of the auth path
    and means a limiter change can never weaken authentication.

    X-Forwarded-For is trusted only in production, where the app sits behind a
    platform proxy that sets it. Trusting it locally would let any client forge a
    fresh identity per request by sending a header.
    """
    identity = "anon"

    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            # A stable, non-reversible-enough handle. The token itself never
            # becomes a dict key, so it cannot be read back out of a heap dump.
            identity = f"tok:{hash(token) & 0xFFFFFFFF:08x}"

    if identity == "anon":
        host = request.client.host if request.client else "unknown"
        if settings.is_production:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                host = forwarded.split(",")[0].strip()
        identity = f"ip:{host}"

    return f"{bucket}:{identity}"


class RateLimit:
    """FastAPI dependency applying one bucket's limits.

    Used as `dependencies=[Depends(rate_limit_ai)]` on a route. Declaring it as a
    dependency rather than middleware means the limit is visible in the route
    definition, and the cheap and expensive routes on one router can differ.
    """

    def __init__(self, bucket: str, *limits: Limit) -> None:
        self.bucket = bucket
        self.limits = limits

    def __call__(self, request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        limiter.check(_client_key(request, self.bucket), self.limits)


def _minute(count: int) -> Limit:
    return Limit(count=count, window_seconds=60)


def _hour(count: int) -> Limit:
    return Limit(count=count, window_seconds=3600)


# Built from settings at import time so a route declares intent, not numbers.
rate_limit_read = RateLimit("read", _minute(settings.RATE_LIMIT_READ_PER_MINUTE))
rate_limit_write = RateLimit("write", _minute(settings.RATE_LIMIT_WRITE_PER_MINUTE))
rate_limit_auth = RateLimit(
    "auth",
    _minute(settings.RATE_LIMIT_AUTH_PER_MINUTE),
    _hour(settings.RATE_LIMIT_AUTH_PER_HOUR),
)
# The expensive one. Both windows apply: the minute limit stops a burst, the hour
# limit stops a slow drip that would still empty a daily quota.
rate_limit_ai = RateLimit(
    "ai",
    _minute(settings.RATE_LIMIT_AI_PER_MINUTE),
    _hour(settings.RATE_LIMIT_AI_PER_HOUR),
)


# --- Baseline, applied to every request ----------------------------------------


def baseline_limits(method: str) -> tuple[str, tuple[Limit, ...]]:
    """The bucket a request falls into when a route declares nothing specific.

    Method is a good enough proxy: a GET is a read, anything else changes state.
    Routes that additionally cost a model call declare `rate_limit_ai`, and both
    apply — the buckets are independent, so an AI call consumes one slot from each.
    """
    if method in ("GET", "HEAD", "OPTIONS"):
        return "read", (_minute(settings.RATE_LIMIT_READ_PER_MINUTE),)
    return "write", (_minute(settings.RATE_LIMIT_WRITE_PER_MINUTE),)
