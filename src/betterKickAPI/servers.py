from __future__ import annotations

import asyncio
import os
import threading
import time
from logging import Logger, getLogger
from logging.handlers import QueueHandler
from typing import TYPE_CHECKING, Any

import socketify

if TYPE_CHECKING:
        import multiprocessing
        from multiprocessing import managers, synchronize

        from betterKickAPI.eventsub.webhook import SSLOptions

__all__ = ["AuthServer", "WebhookServer"]
html = bytes


def _parent_watchdog(stop_event: synchronize.Event, parent_pid: int, logger: Logger, app: socketify.App) -> None:
        try:
                while not stop_event.is_set():
                        try:
                                if os.getppid() != parent_pid:
                                        logger.debug(
                                                "Parent process (PID %d) no longer exists, shutting down",
                                                parent_pid,
                                        )
                                        app.close()
                                        stop_event.set()
                                        return
                                time.sleep(1.0)
                        except OSError as e:  # noqa: PERF203
                                logger.warning("Error checking parent PID: %s", e, exc_info=e)
                                app.close()
                                stop_event.set()
                                return
        except Exception as e:  # noqa: BLE001
                logger.warning("Unexpected error in parent watchdog: %s", e, exc_info=e)
                app.close()
                stop_event.set()
        finally:
                os._exit(0)


def AuthServer(  # noqa: N802
        port: int,
        host: str,
        state: str,
        logger_queue: multiprocessing.Queue,
        shared: managers.DictProxy[Any, Any],
        stop_event: synchronize.Event,
        auth_code_event: synchronize.Event,
) -> None:
        logger = getLogger("kickAPI.servers.auth")
        # logger.setLevel(DEBUG)
        logger.addHandler(QueueHandler(logger_queue))
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
                lambda config: logger.info(
                        "PID (%d) Server started at http://%s:%d",
                        os.getpid(),
                        config.host,
                        config.port,
                ),
        )

        threading.Thread(
                target=_parent_watchdog,
                args=(stop_event, os.getppid(), logger, app),
                daemon=True,
        ).start()

        def waiter() -> None:
                stop_event.wait()
                logger.debug("stop_event set -> closing app")
                # stop_event.clear()
                app.close()

        threading.Thread(target=waiter, daemon=True).start()
        app.run()


def WebhookServer(  # noqa: C901, N802
        port: int,
        host: str,
        logger_queue: multiprocessing.Queue,
        request_queue: multiprocessing.Queue,
        responses: managers.DictProxy[Any, Any],
        # response_event: synchronize.Event,
        stop_event: synchronize.Event,
        endpoint: str,
        ssl_options: SSLOptions | None = None,
) -> None:
        logger = getLogger("kickAPI.servers.webhook")
        # logger.setLevel(DEBUG)
        logger.addHandler(QueueHandler(logger_queue))
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
        header_name = "kick-event-message-id"
        header_name_under = header_name.replace("-", "_")

        async def handle_callback(res: socketify.Response, req: socketify.Request) -> None:
                start = time.time()
                headers = req.get_headers()

                message_id = headers.get(
                        header_name,
                        headers.get(
                                header_name.title(),
                                headers.get(header_name_under, headers.get(header_name_under.title())),
                        ),
                )

                if not isinstance(message_id, str):
                        res.send("Kick-Event-Message-Id was not provided", status=400)
                        return

                body = await res.get_data()
                data = body.getvalue()
                request_queue.put((message_id, data, headers))

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
                except BrokenPipeError as e:
                        msg = f"Shutting down: {e}"
                        logger.error(msg)
                        res.send(msg, status=200)
                        return
                except Exception as e:
                        msg = f"Server error: {e}"
                        logger.exception(msg)
                        res.send(msg, status=500)
                        return

                if not isinstance(response, dict):
                        res.send("Server responded invalid data.", status=500)
                        return

                delta = time.time() - start
                if delta > 1:
                        logger.warning("Server response took %fs", delta)
                res.send(response.get("text", ""), status=response.get("status", 500))

        app = socketify.App(app_options)
        app.get("/", lambda res, _: res.end("pyKickAPI Webhook"))
        app.post(endpoint, handle_callback)
        app.listen(
                socketify.AppListenOptions(port, host),
                lambda config: logger.info(
                        "PID (%d) Server started at http://%s:%d\nWebhook endpoint: %s",
                        os.getpid(),
                        config.host,
                        config.port,
                        endpoint,
                ),
        )

        threading.Thread(
                target=_parent_watchdog,
                args=(stop_event, os.getppid(), logger, app),
                daemon=True,
        ).start()

        def waiter() -> None:
                stop_event.wait()
                logger.debug("stop_event set -> closing app")
                # stop_event.clear()
                app.close()

        threading.Thread(target=waiter, daemon=True).start()
        app.run()
