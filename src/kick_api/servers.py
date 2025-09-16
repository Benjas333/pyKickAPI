from __future__ import annotations

import asyncio
import os
import threading
import time
from logging import Logger, getLogger
from typing import TYPE_CHECKING, Any

import socketify
from pydantic import ValidationError

from kick_api.object.eventsub import WebhookVerificationHeaders

if TYPE_CHECKING:
        import multiprocessing
        from multiprocessing import managers, synchronize

        from kick_api.helper import SSLOptions

__all__ = ["AuthServer", "WebhookServer"]
html = bytes


def _parent_watchdog(stop_event: synchronize.Event, parent_pid: int, logger: Logger, app: socketify.App) -> None:
        try:
                while not stop_event.is_set():
                        try:
                                if os.getppid() != parent_pid:
                                        logger.debug("Parent process (PID %d) no longer exists, shutting down", parent_pid)
                                        app.close()
                                        stop_event.set()
                                        return
                                time.sleep(1.0)
                        except OSError as e:  # noqa: PERF203
                                logger.warning('Error checking parent PID: %s', e)
                                app.close()
                                stop_event.set()
                                return
        except Exception as e:  # noqa: BLE001
                logger.warning('Unexpected error in parent watchdog: %s', e)
                app.close()
                stop_event.set()
        finally:
                os._exit(0)


def AuthServer(  # noqa: N802
        port: int,
        host: str,
        state: str,
        shared: managers.DictProxy[Any, Any],
        stop_event: synchronize.Event,
        auth_code_event: synchronize.Event,
) -> None:
        logger = getLogger("kickAPI.AuthServer")
        document: html = b"""<!DOCTYPE html>
        <html lang="en">
        <head>
                <meta charset="UTF-8">
                <title>pyKickAPI OAuth</title>
        </head>
        <body>
                <h1>Thanks for Authenticating with pyKickAPI!</h1>
                You may now close this page.
        </body>
        </html>"""

        def handle_callback(res: socketify.Response, req: socketify.Request) -> None:
                queries = req.get_queries()
                if not queries:
                        res.send("Queries are missing", status=400)
                        return

                value = queries.get("state", [None])[0]
                logger.debug("Got callback with state %s", value)
                if value != state:
                        res.send("State does not match expected state", status=400)
                        return

                code = queries.get("code", [None])[0]
                if code is None:
                        res.send("Code is missing", status=400)
                        return

                res.send(document, b"text/html; charset=utf-8")

                shared["code"] = code
                auth_code_event.set()

                threading.Timer(0.5, stop_event.set).start()

        app = socketify.App()
        app.get("/", handle_callback)
        app.listen(
                socketify.AppListenOptions(port, host),
                lambda config: logger.debug(
                        "PID (%d) Server started at http://%s:%d",
                        os.getpid(),
                        config.host,
                        config.port,
                ),
        )

        threading.Thread(target=_parent_watchdog, args=(stop_event, os.getppid(), logger, app), daemon=True).start()

        def waiter() -> None:
                stop_event.wait()
                logger.debug("stop_event set -> closing app")
                # stop_event.clear()
                app.close()

        threading.Thread(target=waiter, daemon=True).start()
        app.run()


def WebhookServer(  # noqa: N802
        port: int,
        host: str,
        request_queue: multiprocessing.Queue,
        responses: managers.DictProxy[Any, Any],
        # response_event: synchronize.Event,
        stop_event: synchronize.Event,
        ssl_options: SSLOptions | None = None,
) -> None:
        logger = getLogger("kickAPI.WebhookServer")
        app_options = None
        if ssl_options:
                app_options = socketify.AppOptions(
                        key_file_name=ssl_options.key_file_name,  # type: ignore
                        cert_file_name=ssl_options.cert_file_name,  # type: ignore
                        passphrase=ssl_options.passphrase,  # type: ignore
                        dh_params_file_name=ssl_options.dh_params_file_name,  # type: ignore
                        ca_file_name=ssl_options.ca_file_name,  # type: ignore
                        ssl_ciphers=ssl_options.ssl_ciphers,  # type: ignore
                        ssl_prefer_low_memory_usage=ssl_options.ssl_prefer_low_memory_usage,
                )

        async def handle_callback(res: socketify.Response, req: socketify.Request) -> None:
                try:
                        headers = WebhookVerificationHeaders(**req.get_headers())
                except ValidationError:
                        logger.exception("Parsing headers failed")
                        res.send(b"Invalid headers", status=400)
                        return

                message_id = headers.kick_event_message_id
                if not message_id:
                        res.send("Kick-Event-Message-Id was not provided", status=400)
                        return

                body = await res.get_data()
                data = body.getvalue()
                request_queue.put((message_id, data, headers.model_dump(mode='json')))

                timeout = 30.0
                poll_interval = 0.1
                waited = 0.0
                try:
                        while waited < timeout:
                                if message_id in responses:
                                        response = responses.pop(message_id)
                                        break
                                await asyncio.sleep(poll_interval)
                                waited += poll_interval
                        else:
                                res.send("Server timeout.", status=504)
                                return
                except Exception as e:  # noqa: BLE001
                        res.send(f"Server error: {e}", status=500)
                        return

                if not isinstance(response, dict):
                        res.send("Server responded invalid data.", status=500)
                        return

                res.send(response.get('text', ''), status=response.get('status', 500))

        app = socketify.App(app_options)
        app.get("/", lambda res, _: res.end("pyKickAPI Webhook"))
        app.post("/callback", handle_callback)
        app.listen(
                socketify.AppListenOptions(port, host),
                lambda config: logger.debug(
                        "PID (%d) Server started at http://%s:%d",
                        os.getpid(),
                        config.host,
                        config.port,
                ),
        )

        threading.Thread(target=_parent_watchdog, args=(stop_event, os.getppid(), logger, app), daemon=True).start()

        def waiter() -> None:
                stop_event.wait()
                logger.debug("stop_event set -> closing app")
                # stop_event.clear()
                app.close()

        threading.Thread(target=waiter, daemon=True).start()
        app.run()
