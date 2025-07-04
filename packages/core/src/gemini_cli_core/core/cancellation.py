import asyncio


class CancelSignal:
    """A simple wrapper around asyncio.Event for cancellation."""

    def __init__(self):
        self._event = asyncio.Event()

    def set(self):
        """Signal that cancellation has been requested."""
        self._event.set()

    def is_set(self) -> bool:
        """Check if cancellation has been signaled."""
        return self._event.is_set()

    async def wait(self):
        """Wait until the cancellation is signaled."""
        await self._event.wait()
