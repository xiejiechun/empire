"""Owned local proxy fixture in a separate process from the measured client."""
import asyncio
import base64
from collections import Counter
from time import perf_counter


def run_server(connection, latency):
    asyncio.run(serve(connection, latency))


async def serve(connection, latency):
    from measure_capacity import process_resources

    tasks, writers = set(), set()
    counts, errors, active = Counter(), Counter(), Counter()
    previous, samples = {}, []
    body = b'x' * 32768
    began = perf_counter()
    stopped = asyncio.Event()

    async def proxy(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        writers.add(writer)
        counts['connections_opened'] += 1
        try:
            while True:
                try:
                    header = await reader.readuntil(b'\r\n\r\n')
                except (asyncio.IncompleteReadError, ConnectionError):
                    break
                lines = header.decode('ascii').split('\r\n')
                site = lines[0].split()[1].split('/')[2]
                auth = next(line.split(': ', 1)[1] for line in lines
                            if line.lower().startswith('proxy-authorization:'))
                code = base64.b64decode(auth.split()[1]).decode().split(':', 1)[0]
                key, now = (site, code), perf_counter()
                if active[key]:
                    counts['overlap_violations'] += 1
                if now - previous.get(key, float('-inf')) < 1.99:
                    counts['source_arrival_gap_below_1990ms'] += 1
                previous[key] = now
                active[key] += 1
                try:
                    await asyncio.sleep(latency)
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 32768\r\n'
                                 b'Connection: keep-alive\r\n\r\n' + body)
                    await writer.drain()
                finally:
                    active[key] -= 1
        except (ConnectionError, asyncio.CancelledError):
            pass
        except Exception as exc:
            errors[type(exc).__name__] += 1
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            tasks.discard(task)
            writers.discard(writer)
            counts['connections_closed'] += 1

    async def monitor():
        while not stopped.is_set():
            samples.append(dict(elapsed=perf_counter() - began, **process_resources()))
            await asyncio.sleep(1)

    server = await asyncio.start_server(proxy, '127.0.0.1', 0)
    connection.send(dict(port=server.sockets[0].getsockname()[1]))
    monitor_task = asyncio.create_task(monitor())
    # Only the parent owns this pipe. No per-request IPC enters the benchmark.
    command = await asyncio.to_thread(connection.recv)
    assert command == 'stop'
    server.close()
    handlers = asyncio.gather(*tasks, return_exceptions=True)
    try:
        await asyncio.wait_for(asyncio.shield(handlers), 5)
    except TimeoutError:
        counts['server_connections_not_closed_by_client'] = len(writers)
        for writer in list(writers):
            writer.close()
        await asyncio.wait_for(handlers, 5)
    await asyncio.wait_for(server.wait_closed(), 5)
    stopped.set()
    await monitor_task
    connection.send(dict(counters=dict(counts), errors=dict(errors), resources=samples))
    connection.close()
