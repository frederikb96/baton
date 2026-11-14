"""The throttle forgets clients, so a flood of source addresses cannot grow its memory."""

from __future__ import annotations

from baton.auth import Throttle
from tests.conftest import Clock


def make(clock: Clock, max_clients: int = 10) -> Throttle:
    return Throttle(max_failures=3, window=60, lockout=120, max_clients=max_clients, now=clock)


def test_locks_after_the_limit_and_expires() -> None:
    clock = Clock()
    throttle = make(clock)
    for _ in range(3):
        throttle.fail("a")
    assert throttle.locked("a")
    clock.t += 121
    assert not throttle.locked("a")


def test_quiet_clients_are_forgotten_once_the_bound_is_exceeded() -> None:
    clock = Clock()
    throttle = make(clock)
    for i in range(10):
        throttle.fail(f"old-{i}")
    clock.t += 61
    throttle.fail("new")
    assert set(throttle._failures) == {"new"}


def test_the_table_stays_bounded_while_every_client_is_recent() -> None:
    clock = Clock()
    throttle = make(clock)
    for i in range(1000):
        clock.t += 0.01
        throttle.fail(f"c-{i}")
        assert len(throttle._failures) <= 11
    assert "c-999" in throttle._failures


def test_a_locked_client_survives_the_sweep() -> None:
    clock = Clock()
    throttle = make(clock)
    for _ in range(3):
        throttle.fail("attacker")
    for i in range(30):
        clock.t += 0.01
        throttle.fail(f"c-{i}")
    assert throttle.locked("attacker")
