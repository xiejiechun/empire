import asyncio
import threading

import pytest

from empire.plugins.infra.sql_lane import SQLLane
from tests.test_sql_lane import until


async def test_control_pressure_waits_without_exceeding_capacity_or_replaying():
    lane = SQLLane('control-test', 1, 1)
    release = threading.Event()
    ran = []
    first = asyncio.create_task(lane.call(lambda: release.wait(3)))
    tasks = []
    try:
        await until(lambda: lane.active == 1)
        tasks = [asyncio.create_task(lane.call(lambda i=i: ran.append(i), admission_timeout=2))
                 for i in range(50)]
        await until(lambda: lane.admission_waiting == 49)
        assert lane.pending == 2 and not ran and lane.rejected == 0
        release.set()
        await asyncio.gather(first, *tasks)
        assert sorted(ran) == list(range(50)) and lane.pending == lane.admission_waiting == 0
        assert lane.rejected == 0
    finally:
        release.set()
        await asyncio.gather(first, *tasks, return_exceptions=True)
        await lane.close()


@pytest.mark.parametrize('ending', ['cancel', 'timeout', 'close'])
async def test_unadmitted_work_never_executes_on_cancel_timeout_or_close(ending):
    lane = SQLLane('control-test', 1, 0)
    release = threading.Event()
    ran = []
    first = asyncio.create_task(lane.call(lambda: release.wait(3)))
    task = None
    try:
        await until(lambda: lane.active == 1)
        task = asyncio.create_task(lane.call(lambda: ran.append(True),
                                             admission_timeout=.03 if ending == 'timeout' else 2))
        await until(lambda: lane.admission_waiting == 1)
        if ending == 'cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            if ending == 'close':
                lane.begin_close()
            with pytest.raises(RuntimeError, match='control-test' if ending == 'timeout' else '关闭'):
                await task
        assert not ran and lane.pending == 1 and lane.admission_waiting == 0
    finally:
        release.set()
        await asyncio.gather(first, *([task] if task else []), return_exceptions=True)
        await lane.close()


async def test_admission_deadline_does_not_cancel_an_already_running_write():
    lane = SQLLane('control-test', 1, 0)
    release, completed = threading.Event(), threading.Event()
    def write():
        assert release.wait(3)
        completed.set()
    task = asyncio.create_task(lane.call(write, admission_timeout=.01))
    try:
        await until(lambda: lane.active == 1)
        await asyncio.sleep(.03)
        assert not task.done()
        task.cancel()
        await asyncio.sleep(0)
        assert lane.pending == 1 and not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await lane.close()
