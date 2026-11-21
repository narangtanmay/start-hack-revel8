import threading
import time

from revel8_agent.llm_client import KeyLimiter, LLMPool, LocalLLMError


class FakeClient:
    """Stands in for LocalLLMClient: records concurrency, can 429 on demand."""

    def __init__(self, name, delay=0.05, rate_limited=0):
        self.name, self.delay, self.rate_limited = name, delay, rate_limited
        self.calls = 0
        self.lock = threading.Lock()

    def chat(self, messages, *, json_mode=False, temperature=None, retry_rate_limit=True):
        assert retry_rate_limit is False  # the pool, not the client, handles 429s
        with self.lock:
            self.calls += 1
            if self.rate_limited:
                self.rate_limited -= 1
                raise LocalLLMError("429", status_code=429, retry_after=30)
        time.sleep(self.delay)
        return {"key": self.name}


def make_pool(clients, rpm=20):
    pool = LLMPool.__new__(LLMPool)
    pool.clients, pool.model = clients, "fake"
    pool.limits = [KeyLimiter(rpm) for _ in clients]
    pool.max_wait, pool._lock = 5.0, threading.Lock()
    return pool


def test_limiter_window():
    L = KeyLimiter(2, window=10)
    L.sent.extend([0.0, 1.0])
    assert L.wait(5.0) == 5.0      # full until the first request leaves the window
    assert L.wait(10.0) == 0.0


def test_parallel_calls_spread_over_all_keys():
    clients = [FakeClient(f"k{i}", delay=0.2) for i in range(4)]
    pool = make_pool(clients, rpm=3)
    t0 = time.monotonic()
    threads = [threading.Thread(target=pool.lane(0).chat, args=([],)) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert [c.calls for c in clients] == [3, 3, 3, 3]   # lane 0 overflowed onto every key
    assert time.monotonic() - t0 < 1.0                  # ran concurrently, not 12 x 0.2 s


def test_429_moves_to_another_key_without_sleeping():
    clients = [FakeClient("k0", rate_limited=1), FakeClient("k1")]
    pool = make_pool(clients)
    t0 = time.monotonic()
    assert pool.lane(0).chat([]) == {"key": "k1"}
    assert time.monotonic() - t0 < 0.5
    assert pool.limits[0].cooldown_until > time.monotonic() + 20  # k0 parked for its retry-after
    assert pool.lane(0).chat([]) == {"key": "k1"}                   # and skipped while parked


def test_bad_request_is_not_retried_on_other_keys():
    class Bad(FakeClient):
        def chat(self, *a, **k):
            self.calls += 1
            raise LocalLLMError("400", status_code=400)
    clients = [Bad("k0"), Bad("k1")]
    pool = make_pool(clients)
    try:
        pool.lane(0).chat([])
    except LocalLLMError as e:
        assert e.status_code == 400
    assert sum(c.calls for c in clients) == 1
