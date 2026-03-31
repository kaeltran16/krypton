import pytest


class FakeRedis:
    """Minimal async Redis mock with pipeline support for engine tests."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def incr(self, key: str):
        val = int(self.store.get(key, "0")) + 1
        self.store[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int):
        pass

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops: list = []

    def incr(self, key: str):
        self._ops.append(("incr", key))

    def set(self, key: str, value: str):
        self._ops.append(("set", key, value))

    def delete(self, key: str):
        self._ops.append(("delete", key))

    def expire(self, key: str, seconds: int):
        pass

    async def execute(self):
        for op in self._ops:
            if op[0] == "incr":
                val = int(self._redis.store.get(op[1], "0")) + 1
                self._redis.store[op[1]] = str(val)
            elif op[0] == "set":
                self._redis.store[op[1]] = op[2]
            elif op[0] == "delete":
                self._redis.store.pop(op[1], None)


@pytest.fixture
def fake_redis():
    return FakeRedis()
