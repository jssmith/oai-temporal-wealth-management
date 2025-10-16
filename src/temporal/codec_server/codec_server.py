from functools import partial
from typing import Awaitable, Callable, Iterable, List
import os

from aiohttp import hdrs, web
from google.protobuf import json_format
from temporalio.api.common.v1 import Payload, Payloads

from src.temporal.claim_check.claim_check_codec import ClaimCheckCodec
from src.common.db2_config import DB2Config
from common.util import str_to_bool


def build_codec_server() -> web.Application:
    # Cors handler
    async def cors_options(req: web.Request) -> web.Response:
        resp = web.Response()
        if req.headers.get(hdrs.ORIGIN) == "http://localhost:8233":
            resp.headers[hdrs.ACCESS_CONTROL_ALLOW_ORIGIN] = "http://localhost:8233"
            resp.headers[hdrs.ACCESS_CONTROL_ALLOW_METHODS] = "POST"
            resp.headers[hdrs.ACCESS_CONTROL_ALLOW_HEADERS] = "content-type,x-namespace"
        return resp

    # General purpose payloads-to-payloads
    async def apply(
        fn: Callable[[Iterable[Payload]], Awaitable[List[Payload]]], req: web.Request
    ) -> web.Response:
        # Read payloads as JSON
        assert req.content_type == "application/json"
        data = await req.read()
        payloads = json_format.Parse(data, Payloads())
        # print("----- Request -------")
        # print(payloads)
        # print("---------------------")
        # Apply
        payloads = Payloads(payloads=await fn(payloads.payloads))

        # Apply CORS and return JSON
        resp = await cors_options(req)
        resp.content_type = "application/json"
        resp.text = json_format.MessageToJson(payloads)
        # print("------ Response -----")
        # print(f"{resp.text}")
        # print("---------------------")

        return resp

    # Build app with same configuration as the plugin
    db2_config = DB2Config()
    ttl_hours = int(os.getenv("CLAIM_CHECK_TTL_HOURS", "1440"))
    enable_compression = str_to_bool(os.getenv("CLAIM_CHECK_COMPRESSION", "True"))
    compression_threshold = int(os.getenv("CLAIM_CHECK_COMPRESSION_THRESHOLD", "250"))

    codec = ClaimCheckCodec(
        config=db2_config,
        ttl_hours=ttl_hours,
        enable_compression=enable_compression,
        compression_threshold=compression_threshold,
    )
    app = web.Application()
    app.add_routes(
        [
            web.post("/encode", partial(apply, codec.encode)),
            web.post("/decode", partial(apply, codec.decode)),
            web.options("/decode", cors_options),
        ]
    )
    return app


if __name__ == "__main__":
    web.run_app(build_codec_server(), host="127.0.0.1", port=8081)
