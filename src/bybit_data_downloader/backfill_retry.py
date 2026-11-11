"""Cold retry policy v1: bounded attempts, full jitter, Retry-After minimum."""
import json
import math
import random
import sys
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import httpx

TRANSIENT = (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError)


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0

    def __post_init__(self):
        if self.attempts < 1 or any(not math.isfinite(v) or v < 0 for v in (self.base_delay, self.max_delay)):
            raise ValueError("Retry attempts must be positive and delays finite and nonnegative")

    def run(self, operation, target):
        ceiling = min(self.base_delay, self.max_delay)
        for attempt in range(1, self.attempts + 1):
            try:
                return operation()
            except (httpx.HTTPStatusError, *TRANSIENT) as error:
                response = error.response if isinstance(error, httpx.HTTPStatusError) else None
                if response is not None and response.status_code != 429 and not 500 <= response.status_code <= 599:
                    raise
                if attempt == self.attempts:
                    raise
                wait = random.uniform(0, ceiling)
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
                print(json.dumps(dict(event="retry", target=target, attempt=attempt,
                                      exception=type(error).__name__, wait_seconds=wait)), file=sys.stderr, flush=True)
                time.sleep(wait)
                ceiling = min(self.max_delay, ceiling * 2)
