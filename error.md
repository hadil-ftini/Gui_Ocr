PS C:\Users\Hedyl\Desktop\PFE\New folder> python .\plc_simulator.py
2026-02-17 21:58:22,235 [INFO] PLCSimulator: Starting Modbus TCP server on 192.168.0.50:3000
2026-02-17 21:58:22,237 [ERROR] PLCSimulator: Server error: asyncio.run() cannot be called from a running event loop
Traceback (most recent call last):
  File "C:\Users\Hedyl\Desktop\PFE\New folder\plc_simulator.py", line 76, in run_server
    asyncio.run(async_run())
  File "C:\Users\Hedyl\AppData\Local\Programs\Python\Python310\lib\asyncio\runners.py", line 44, in run
    return loop.run_until_complete(main)
  File "C:\Users\Hedyl\AppData\Local\Programs\Python\Python310\lib\asyncio\base_events.py", line 649, in run_until_complete
    return future.result()
  File "C:\Users\Hedyl\Desktop\PFE\New folder\plc_simulator.py", line 74, in async_run
    await StartTcpServer(context=self.context, identity=self.identity, address=(self.host, self.port))
  File "C:\Users\Hedyl\AppData\Local\Programs\Python\Python310\lib\site-packages\pymodbus\server\async_io.py", line 722, in StartTcpServer
    return asyncio.run(StartAsyncTcpServer(**kwargs))
  File "C:\Users\Hedyl\AppData\Local\Programs\Python\Python310\lib\asyncio\runners.py", line 33, in run
    raise RuntimeError(
RuntimeError: asyncio.run() cannot be called from a running event loop
C:\Users\Hedyl\AppData\Local\Programs\Python\Python310\lib\ctypes\__init__.py:8: RuntimeWarning: coroutine 'StartAsyncTcpServer' was never awaited
  from _ctypes import Union, Structure, Array
RuntimeWarning: Enable tracemalloc to get the object allocation traceback