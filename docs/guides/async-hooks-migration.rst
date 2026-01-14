====================================
Migrating to Async/Await Hooks
====================================

.. note::
   **New in v3.9.0**: ActingWeb hooks now support native async/await syntax.

This guide helps you migrate existing synchronous hooks to async/await patterns and explains when and why to use async hooks.

Why Use Async Hooks?
====================

Async hooks provide significant performance benefits for I/O-bound operations:

**Without Async (Synchronous)**::

   Request 1: [===HTTP===] (waits)           [done]
   Request 2:                [===HTTP===]    (waits) [done]
   Request 3:                                [===HTTP===] (waits) [done]
   Total time: ~3 seconds

**With Async (Concurrent)**::

   Request 1: [===HTTP===]                   [done]
   Request 2: [===HTTP===]                   [done]
   Request 3: [===HTTP===]                   [done]
   Total time: ~1 second

Use Cases for Async Hooks
==========================

**Perfect for Async:**

- External HTTP/API calls (aiohttp, httpx)
- Database queries (asyncpg, motor)
- AWS services (aioboto3, async Bedrock)
- File I/O operations
- AwProxy async methods

**Keep Synchronous:**

- Simple calculations
- Data transformations
- Quick dictionary lookups
- CPU-intensive operations

Migration Guide
===============

Step 1: Identify I/O-Bound Hooks
---------------------------------

Look for hooks that:

- Make HTTP requests
- Query databases
- Read/write files
- Call external services

**Example** - Before (Synchronous)::

   import requests

   @app.method_hook("fetch_weather")
   def get_weather(actor, method_name, data):
       # Blocks while waiting for response
       response = requests.get(f"https://api.weather.com/v1/forecast?city={data['city']}")
       return response.json()

Step 2: Convert to Async
-------------------------

Replace sync libraries with async equivalents:

**After (Asynchronous)**::

   import aiohttp

   @app.method_hook("fetch_weather")
   async def get_weather(actor, method_name, data):
       # Non-blocking, allows other requests to process
       async with aiohttp.ClientSession() as session:
           async with session.get(f"https://api.weather.com/v1/forecast?city={data['city']}") as resp:
               return await resp.json()

Step 3: Update Library Dependencies
------------------------------------

Install async versions of your libraries:

.. code-block:: bash

   # HTTP clients
   pip install aiohttp httpx

   # Database
   pip install asyncpg motor  # PostgreSQL, MongoDB

   # AWS
   pip install aioboto3

Common Library Replacements
----------------------------

+-----------------------+------------------------+
| Sync Library          | Async Alternative      |
+=======================+========================+
| ``requests``          | ``aiohttp``, ``httpx`` |
+-----------------------+------------------------+
| ``psycopg2``          | ``asyncpg``            |
+-----------------------+------------------------+
| ``pymongo``           | ``motor``              |
+-----------------------+------------------------+
| ``boto3``             | ``aioboto3``           |
+-----------------------+------------------------+
| ``redis-py`` (sync)   | ``redis`` (async mode) |
+-----------------------+------------------------+

Real-World Examples
===================

Example 1: Database Query
--------------------------

**Before (Synchronous)**::

   import psycopg2

   @app.property_hook("user_profile")
   def get_profile(actor, operation, value, path):
       if operation == "get":
           conn = psycopg2.connect("dbname=mydb")
           cursor = conn.cursor()
           cursor.execute("SELECT * FROM profiles WHERE actor_id = %s", (actor.id,))
           profile = cursor.fetchone()
           conn.close()
           return dict(profile) if profile else None
       return value

**After (Asynchronous)**::

   import asyncpg

   @app.property_hook("user_profile")
   async def get_profile(actor, operation, value, path):
       if operation == "get":
           conn = await asyncpg.connect("postgresql://localhost/mydb")
           profile = await conn.fetchrow(
               "SELECT * FROM profiles WHERE actor_id = $1",
               actor.id
           )
           await conn.close()
           return dict(profile) if profile else None
       return value

Example 2: Multiple HTTP Calls
-------------------------------

**Before (Sequential, Slow)**::

   import requests

   @app.method_hook("aggregate_data")
   def aggregate(actor, method_name, data):
       # Takes 3+ seconds (sequential)
       weather = requests.get("https://api.weather.com/...").json()
       news = requests.get("https://api.news.com/...").json()
       stocks = requests.get("https://api.stocks.com/...").json()

       return {
           "weather": weather,
           "news": news,
           "stocks": stocks
       }

**After (Concurrent, Fast)**::

   import aiohttp
   import asyncio

   @app.method_hook("aggregate_data")
   async def aggregate(actor, method_name, data):
       # Takes ~1 second (concurrent)
       async with aiohttp.ClientSession() as session:
           weather_task = session.get("https://api.weather.com/...")
           news_task = session.get("https://api.news.com/...")
           stocks_task = session.get("https://api.stocks.com/...")

           weather_resp, news_resp, stocks_resp = await asyncio.gather(
               weather_task, news_task, stocks_task
           )

           return {
               "weather": await weather_resp.json(),
               "news": await news_resp.json(),
               "stocks": await stocks_resp.json()
           }

Example 3: Peer Communication with AwProxy
-------------------------------------------

**Before (Synchronous)**::

   from actingweb.interface import AwProxy

   @app.action_hook("notify_peers")
   def notify(actor, action_name, data):
       proxy = AwProxy(config)

       for peer in actor.trust.get_peers():
           # Blocks on each request
           proxy.send_message(
               peer_url=peer.url,
               message=data["message"],
               secret=peer.secret
           )

       return {"notified": len(actor.trust.get_peers())}

**After (Asynchronous)**::

   from actingweb.interface import AwProxy
   import asyncio

   @app.action_hook("notify_peers")
   async def notify(actor, action_name, data):
       proxy = AwProxy(config)
       peers = actor.trust.get_peers()

       # Send all messages concurrently
       tasks = [
           proxy.send_message_async(
               peer_url=peer.url,
               message=data["message"],
               secret=peer.secret
           )
           for peer in peers
       ]

       results = await asyncio.gather(*tasks)
       return {"notified": len([r for r in results if r is not None])}

Mixed Sync and Async
====================

You can use both sync and async hooks in the same application:

.. code-block:: python

   # Quick synchronous operation - keep sync
   @app.method_hook("add_numbers")
   def quick_calc(actor, method_name, data):
       return {"sum": data["x"] + data["y"]}

   # Slow I/O operation - use async
   @app.method_hook("fetch_data")
   async def fetch(actor, method_name, data):
       async with aiohttp.ClientSession() as session:
           async with session.get(data["url"]) as resp:
               return {"data": await resp.text()}

   # Database query - use async
   @app.property_hook("user_settings")
   async def settings(actor, operation, value, path):
       if operation == "get":
           conn = await asyncpg.connect("postgresql://...")
           settings = await conn.fetchval(
               "SELECT settings FROM users WHERE id = $1",
               actor.id
           )
           await conn.close()
           return settings
       return value

The framework automatically detects whether each hook is sync or async and executes it appropriately.

Testing Async Hooks
====================

Use pytest-asyncio for testing:

.. code-block:: python

   # conftest.py
   pytest_plugins = ("pytest_asyncio",)

   # test_hooks.py
   import pytest

   @pytest.mark.asyncio
   async def test_async_method_hook(app, test_actor):
       """Test async method hook execution."""

       @app.method_hook("test_method")
       async def async_hook(actor, method_name, data):
           await asyncio.sleep(0.01)  # Simulate async I/O
           return {"result": "success"}

       # Test via async execution
       result = await app.hooks.execute_method_hooks_async(
           "test_method",
           test_actor,
           {}
       )

       assert result == {"result": "success"}

Framework-Specific Notes
========================

FastAPI
-------

**Best Performance**: FastAPI automatically uses async handlers (``AsyncMethodsHandler``, ``AsyncActionsHandler``) when available.

- Async hooks execute natively without thread pool
- True concurrent request handling
- Optimal for high-throughput APIs

.. code-block:: python

   from fastapi import FastAPI
   from actingweb.interface import ActingWebApp

   app = ActingWebApp(...)
   fastapi = FastAPI()

   # Register async hooks
   @app.method_hook("fetch_data")
   async def fetch(actor, method_name, data):
       # Executes natively in FastAPI event loop
       ...

   app.integrate_fastapi(fastapi)

Flask
-----

**Compatibility Mode**: Flask uses ``asyncio.run()`` to execute async hooks.

- Async hooks work but aren't truly concurrent
- Still allows using async libraries
- Good for gradual migration

.. code-block:: python

   from flask import Flask
   from actingweb.interface import ActingWebApp

   app = ActingWebApp(...)
   flask = Flask(__name__)

   # Register async hooks
   @app.method_hook("fetch_data")
   async def fetch(actor, method_name, data):
       # Executed via asyncio.run()
       ...

   app.integrate_flask(flask)

Performance Tips
================

1. **Use Connection Pools**

   Don't create new connections per request:

   .. code-block:: python

      # Bad: Creates new connection each time
      @app.method_hook("query")
      async def bad_query(actor, method_name, data):
          conn = await asyncpg.connect("...")  # Expensive!
          result = await conn.fetch("...")
          await conn.close()
          return result

      # Good: Use connection pool
      pool = await asyncpg.create_pool("...")

      @app.method_hook("query")
      async def good_query(actor, method_name, data):
          async with pool.acquire() as conn:  # Reuses connections
              result = await conn.fetch("...")
          return result

2. **Batch Operations with asyncio.gather()**

   Process multiple items concurrently:

   .. code-block:: python

      @app.method_hook("process_batch")
      async def process(actor, method_name, data):
          tasks = [process_item(item) for item in data["items"]]
          results = await asyncio.gather(*tasks)
          return {"results": results}

3. **Don't Block the Event Loop**

   Never use blocking calls in async hooks:

   .. code-block:: python

      # Bad: Blocks event loop
      @app.method_hook("bad")
      async def bad(actor, method_name, data):
          time.sleep(1)  # Blocks everything!
          return {}

      # Good: Use async sleep
      @app.method_hook("good")
      async def good(actor, method_name, data):
          await asyncio.sleep(1)  # Non-blocking
          return {}

Troubleshooting
===============

"RuntimeError: asyncio.run() cannot be called from a running event loop"
------------------------------------------------------------------------

This happens when you call sync hook execution from an async context.

**Solution**: Use the async execution methods:

.. code-block:: python

   # Wrong
   result = hooks.execute_method_hooks(...)  # In async context

   # Right
   result = await hooks.execute_method_hooks_async(...)

"Task was destroyed but it is pending"
---------------------------------------

Ensure all async operations complete before exiting:

.. code-block:: python

   @app.method_hook("cleanup")
   async def cleanup(actor, method_name, data):
       tasks = [do_something_async() for _ in range(10)]
       await asyncio.gather(*tasks)  # Wait for all
       return {"done": True}

Performance Not Improving
--------------------------

Check that you're:

1. Using FastAPI (not Flask) for true async
2. Actually making concurrent calls (use ``asyncio.gather()``)
3. Using async libraries (not sync libraries in async functions)
4. Not blocking with ``time.sleep()`` or sync database calls

Migration Checklist
===================

Before deploying async hooks to production:

☐ Identify I/O-bound hooks worth migrating

☐ Install async library dependencies

☐ Convert hooks to ``async def``

☐ Replace sync library calls with async equivalents

☐ Test with pytest-asyncio

☐ Verify error handling still works

☐ Check performance improvements

☐ Deploy to staging first

☐ Monitor for "event loop" errors

☐ Verify backward compatibility with existing sync hooks

Further Reading
===============

- :doc:`hooks` - General hooks guide
- :doc:`../reference/hooks-reference` - Complete hooks reference with async examples
- `Python asyncio documentation <https://docs.python.org/3/library/asyncio.html>`_
- `FastAPI async support <https://fastapi.tiangolo.com/async/>`_
