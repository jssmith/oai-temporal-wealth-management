from importlib.metadata import metadata

import gzip
import logging
import uuid
import redis.asyncio as redis
from typing import Iterable, List

from temporalio.api.common.v1 import Payload
from temporalio.converter import PayloadCodec

#
# Substitutes the payload for a GUID
# and stores the original payload in Redis
#
class ClaimCheckCodec(PayloadCodec):

    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379, enable_compression: bool = True, compression_threshold: int = 250):
        self.redis_client = redis.Redis(host=redis_host, port=redis_port)
        self.enable_compression = enable_compression
        self.compression_threshold = compression_threshold
        self.logger = logging.getLogger(__name__)

    #
    # TODO: Figure out when/how to close the redis_client
    #       Can't be done in a __del__ as it aClose() needs to be awaited
    #
    async def encode(self, payloads: Iterable[Payload]) -> List[Payload]:
        out: list[Payload] = []
        for p in payloads:
            encoded = await self.encode_payload(p)
            out.append(encoded)

        return out

    async def decode(self, payloads: Iterable[Payload]) -> List[Payload]:
        out: List[Payload] = []
        for p in payloads:
            codec_version = p.metadata.get("temporal.io/claim-check-codec", b"").decode()
            if codec_version not in ["v1", "v1c"]:
                # Not a claim check payload, pass through unchanged
                out.append(p)
                continue

            redis_id = p.data.decode("utf-8")
            value = await self.redis_client.get(redis_id)
            
            # Decompress if this is a v1c (compressed) payload
            if codec_version == "v1c":
                compressed_size = len(value)
                value = gzip.decompress(value)
                decompressed_size = len(value)
                compression_ratio = (1 - compressed_size / decompressed_size) * 100 if decompressed_size > 0 else 0
                self.logger.info(f"Claim check decode: {compressed_size} bytes -> {decompressed_size} bytes (was compressed: {compression_ratio:.1f}%)")
            else:
                self.logger.info(f"Claim check decode: {len(value)} bytes (uncompressed)")
            
            new_payload = Payload.FromString(value)
            out.append(new_payload)
        return out

    async def encode_payload(self, payload: Payload) -> Payload:
        id = str(uuid.uuid4())
        value = payload.SerializeToString()
        original_size = len(value)
        
        # Compress the serialized payload if compression is enabled and payload is above threshold
        should_compress = self.enable_compression and original_size >= self.compression_threshold
        
        if should_compress:
            value = gzip.compress(value)
            compressed_size = len(value)
            compression_ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
            codec_version = b"v1c"  # v1c indicates compressed
            self.logger.info(f"Claim check encode: {original_size} bytes -> {compressed_size} bytes (compression: {compression_ratio:.1f}%)")
        else:
            codec_version = b"v1"  # v1 indicates uncompressed
            if self.enable_compression and original_size < self.compression_threshold:
                self.logger.info(f"Claim check encode: {original_size} bytes (skipped compression, below {self.compression_threshold} byte threshold)")
            else:
                self.logger.info(f"Claim check encode: {original_size} bytes (compression disabled)")
        
        await self.redis_client.set(id, value)
        out = Payload(
            metadata= {
                "encoding": b"claim-checked",
                "temporal.io/claim-check-codec": codec_version,
            },
            data=id.encode("utf-8"),
        )
        return out
