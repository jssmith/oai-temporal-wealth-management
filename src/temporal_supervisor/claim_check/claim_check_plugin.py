import os

from temporalio.client import Plugin, ClientConfig
from temporalio.converter import DataConverter

from common.util import str_to_bool
from temporal_supervisor.claim_check.claim_check_codec import ClaimCheckCodec

class ClaimCheckPlugin(Plugin):
    def __init__(self):
        self.useClaimCheck = str_to_bool(os.getenv("USE_CLAIM_CHECK", "False"))
        self.redisHost = os.getenv("REDIS_HOST", "localhost")
        self.redisPort = int(os.getenv("REDIS_PORT", "6379"))
        self.enableCompression = str_to_bool(os.getenv("CLAIM_CHECK_COMPRESSION", "True"))
        self.compressionThreshold = int(os.getenv("CLAIM_CHECK_COMPRESSION_THRESHOLD", "250"))

    def get_data_converter(self, config: ClientConfig) -> DataConverter:
        default_converter_class = config["data_converter"].payload_converter_class
        if self.useClaimCheck:
            print(f"using claim check codec {self.useClaimCheck} with compression {self.enableCompression} (threshold: {self.compressionThreshold} bytes)")
            claim_check_codec = ClaimCheckCodec(self.redisHost, self.redisPort, self.enableCompression, self.compressionThreshold)

            return DataConverter(
                payload_converter_class=default_converter_class,
                payload_codec=claim_check_codec,
            )
        else:
            return DataConverter(
                payload_converter_class=default_converter_class
            )

    def configure_client(self, config: ClientConfig) -> ClientConfig:
        return super().configure_client(config)


