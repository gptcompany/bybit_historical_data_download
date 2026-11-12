"""Cold retry policy v1: bounded attempts, full jitter, Retry-After minimum."""
import math
import random
import sys
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import httpx
from scripts.cold_deploy import emit

# Public market GETs: https://bybit-exchange.github.io/docs/v5/error
BYBIT_TRANSIENT = {429, 10000, 10006, 10016}


class BybitAPIError(ValueError):
    """Upstream status without its untrusted message or response body."""

    def __init__(self, code, response):
        super().__init__(f"Bybit API retCode {code}")
        self.code = code
        self.response = response


TRANSIENT = (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError)


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0

    def __post_init__(self):
        if self.attempts < 1 or any(not math.isfinite(v) or v < 0 for v in (self.base_delay, self.max_delay)):
            raise ValueError("Retry attempts must be positive and delays finite and nonnegative")

    def run(self, operation, target, *, on_retry=None, emission_state=None):
        state = {} if emission_state is None else emission_state
        ceiling = min(self.base_delay, self.max_delay)
        for attempt in range(1, self.attempts + 1):
            try:
                return operation()
            except (BybitAPIError, httpx.HTTPStatusError, *TRANSIENT) as error:
                api_error = isinstance(error, BybitAPIError)
                response = error.response if isinstance(error, (BybitAPIError, httpx.HTTPStatusError)) else None
                if api_error and error.code not in BYBIT_TRANSIENT:
                    raise
                if not api_error and response is not None and response.status_code != 429 and not 500 <= response.status_code <= 599:
                    raise
                if attempt == self.attempts:
                    raise
                wait = ceiling if api_error else random.uniform(0, ceiling)
                if response is not None and "Retry-After" in response.headers:
                    value = response.headers["Retry-After"]
                    try:
                        try:
                            minimum = float(value)
                        except ValueError:
                            minimum = parsedate_to_datetime(value).timestamp() - time.time()
                        if math.isfinite(minimum):
                            wait = max(wait, minimum)
                    except (ValueError, TypeError, OverflowError):
                        pass  # Invalid upstream metadata does not suppress the bounded retry.
                event = dict(event="retry", target=target, attempt=attempt,
                             exception=type(error).__name__, wait_seconds=wait)
                if on_retry is not None:
                    on_retry(event)
                emit(event, state, stream=sys.stderr, event=True)
                time.sleep(wait)
                ceiling = min(self.max_delay, ceiling * 2)
