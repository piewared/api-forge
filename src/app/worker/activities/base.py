# worker/activities/base.py
import asyncio

from temporalio import activity


def cpu_bound_concurrency(default: int = 2):
    # helper for setting sensible ACT concurrency based on vCPU; can be read by registry
    ...


@activity.defn
async def heartbeat_sleep(seconds: int):
    for _ in range(seconds):
        activity.heartbeat({"progress": _})
        await asyncio.sleep(1)
