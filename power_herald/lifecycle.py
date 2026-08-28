"""Shared lifecycle helpers for standalone workers and the combined server."""

import asyncio
import signal


def create_stop_event() -> asyncio.Event:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass
    return stop_event


def use_stop_event(stop_event: asyncio.Event | None) -> asyncio.Event:
    return stop_event if stop_event is not None else create_stop_event()