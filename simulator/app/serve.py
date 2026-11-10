"""Runs the processor API (8100) and the control API (8101) in one process."""

import asyncio

import uvicorn

from .apps import control_app, processor_app


async def main() -> None:
    servers = [
        uvicorn.Server(uvicorn.Config(processor_app, host="0.0.0.0", port=8100)),
        uvicorn.Server(uvicorn.Config(control_app, host="0.0.0.0", port=8101)),
    ]
    await asyncio.gather(*(server.serve() for server in servers))


if __name__ == "__main__":
    asyncio.run(main())
