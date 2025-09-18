import asyncio
import dataclasses
import gzip
import json
import logging
import pytest
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List

from temporalio import workflow, activity
from temporalio.api.common.v1 import Payload
from temporalio.client import Client
from temporalio.converter import DataConverter
from temporalio.worker import Worker

from temporal_supervisor.claim_check.claim_check_codec import ClaimCheckCodec
from temporal_supervisor.claim_check.claim_check_plugin import ClaimCheckPlugin


@dataclass
class LargeTestData:
    """Test data class that creates large payloads suitable for compression testing."""
    user_id: str
    items: List[Dict[str, Any]]
    metadata: Dict[str, Any]


@dataclass
class SimpleTestData:
    """Simple test data for basic functionality testing."""
    message: str
    count: int


@activity.defn
async def process_large_data(data: LargeTestData) -> str:
    """Activity that processes large data to test claim check with compression."""
    return f"Processed {len(data.items)} items for user {data.user_id}"


@activity.defn
async def process_simple_data(data: SimpleTestData) -> str:
    """Activity that processes simple data."""
    return f"Message: {data.message}, Count: {data.count}"


@workflow.defn
class ClaimCheckTestWorkflow:
    """Test workflow that uses activities with large payloads."""
    
    @workflow.run
    async def run(self, test_data: LargeTestData) -> str:
        # Process the large data through an activity
        result = await workflow.execute_activity(
            process_large_data,
            test_data,
            start_to_close_timeout=timedelta(seconds=30)
        )
        
        # Also test with simple data
        simple_data = SimpleTestData(message="test", count=42)
        simple_result = await workflow.execute_activity(
            process_simple_data,
            simple_data,
            start_to_close_timeout=timedelta(seconds=30)
        )
        
        return f"{result} | {simple_result}"


@workflow.defn
class SimpleTestWorkflow:
    """Simple workflow for testing basic claim check functionality."""
    
    @workflow.run
    async def run(self, data: SimpleTestData) -> SimpleTestData:
        # Return the same data to test round-trip encoding/decoding
        return data


# Shared fixtures for both test classes
@pytest.fixture
def large_test_data() -> LargeTestData:
    """Create large test data that will benefit from compression."""
    items = []
    for i in range(100):
        items.append({
            "id": i,
            "name": f"Item {i}",
            "description": "This is a sample item with a long description that repeats many times to create a large payload that will compress well. " * 5,
            "category": "test_category",
            "tags": ["tag1", "tag2", "tag3", "sample", "test", "compression", "temporal"],
            "properties": {
                "color": "blue",
                "size": "large",
                "weight": 10.5,
                "material": "cotton",
                "origin": "test_factory"
            },
            "metadata": {
                "created_by": "test_user",
                "created_at": "2023-01-01T00:00:00Z",
                "status": "active",
                "version": 1
            }
        })
    
    return LargeTestData(
        user_id="test-user-12345",
        items=items,
        metadata={
            "session_id": "session-" + str(uuid.uuid4()),
            "request_time": "2023-01-01T00:00:00Z",
            "client_info": {
                "browser": "test-browser",
                "version": "1.0.0",
                "platform": "test-platform"
            }
        }
    )


@pytest.fixture
def simple_test_data() -> SimpleTestData:
    """Create simple test data."""
    return SimpleTestData(message="Hello, Temporal!", count=123)


class TestClaimCheckCodec:
    """Test suite for ClaimCheckCodec with compression functionality in workflow context."""

    @pytest.mark.asyncio
    async def test_workflow_with_compression_enabled(self, client: Client, large_test_data: LargeTestData):
        """Test workflow execution with claim check compression enabled."""
        # Create client with claim check codec (compression enabled by default)
        claim_check_codec = ClaimCheckCodec(enable_compression=True)
        
        try:
            # Replace data converter with claim check codec
            new_config = client.config()
            new_config["data_converter"] = dataclasses.replace(
                DataConverter.default, 
                payload_codec=claim_check_codec
            )
            client_with_codec = Client(**new_config)
            
            task_queue = f"tq-claim-check-compressed-{uuid.uuid4()}"
            
            # Start worker with the codec
            async with Worker(
                client_with_codec,
                task_queue=task_queue,
                workflows=[ClaimCheckTestWorkflow],
                activities=[process_large_data, process_simple_data]
            ):
                # Execute workflow with large data
                result = await client_with_codec.execute_workflow(
                    ClaimCheckTestWorkflow.run,
                    large_test_data,
                    id=f"wf-claim-check-compressed-{uuid.uuid4()}",
                    task_queue=task_queue,
                )
                
                # Verify the result
                assert "Processed 100 items for user test-user-12345" in result
                assert "Message: test, Count: 42" in result
                
        finally:
            await claim_check_codec.redis_client.aclose()

    @pytest.mark.asyncio
    async def test_workflow_with_compression_disabled(self, client: Client, large_test_data: LargeTestData):
        """Test workflow execution with claim check compression disabled."""
        # Create client with claim check codec (compression disabled)
        claim_check_codec = ClaimCheckCodec(enable_compression=False)
        
        try:
            # Replace data converter with claim check codec
            new_config = client.config()
            new_config["data_converter"] = dataclasses.replace(
                DataConverter.default, 
                payload_codec=claim_check_codec
            )
            client_with_codec = Client(**new_config)
            
            task_queue = f"tq-claim-check-uncompressed-{uuid.uuid4()}"
            
            # Start worker with the codec
            async with Worker(
                client_with_codec,
                task_queue=task_queue,
                workflows=[ClaimCheckTestWorkflow],
                activities=[process_large_data, process_simple_data]
            ):
                # Execute workflow with large data
                result = await client_with_codec.execute_workflow(
                    ClaimCheckTestWorkflow.run,
                    large_test_data,
                    id=f"wf-claim-check-uncompressed-{uuid.uuid4()}",
                    task_queue=task_queue,
                )
                
                # Verify the result
                assert "Processed 100 items for user test-user-12345" in result
                assert "Message: test, Count: 42" in result
                
        finally:
            await claim_check_codec.redis_client.aclose()

    @pytest.mark.asyncio
    async def test_round_trip_data_integrity(self, client: Client, simple_test_data: SimpleTestData):
        """Test that data maintains integrity through encode/decode cycle."""
        claim_check_codec = ClaimCheckCodec(enable_compression=True)
        
        try:
            # Replace data converter with claim check codec
            new_config = client.config()
            new_config["data_converter"] = dataclasses.replace(
                DataConverter.default, 
                payload_codec=claim_check_codec
            )
            client_with_codec = Client(**new_config)
            
            task_queue = f"tq-round-trip-{uuid.uuid4()}"
            
            # Start worker with the codec
            async with Worker(
                client_with_codec,
                task_queue=task_queue,
                workflows=[SimpleTestWorkflow]
            ):
                # Execute workflow that returns the same data
                result = await client_with_codec.execute_workflow(
                    SimpleTestWorkflow.run,
                    simple_test_data,
                    id=f"wf-round-trip-{uuid.uuid4()}",
                    task_queue=task_queue,
                )
                
                # Verify the data is identical
                assert result.message == simple_test_data.message
                assert result.count == simple_test_data.count
                assert result == simple_test_data
                
        finally:
            await claim_check_codec.redis_client.aclose()

    @pytest.mark.asyncio
    async def test_compression_logging(self, client: Client, large_test_data: LargeTestData, caplog):
        """Test that compression statistics are logged during workflow execution."""
        # Set logging level to capture INFO logs
        caplog.set_level(logging.INFO)
        
        claim_check_codec = ClaimCheckCodec(enable_compression=True)
        
        try:
            # Replace data converter with claim check codec
            new_config = client.config()
            new_config["data_converter"] = dataclasses.replace(
                DataConverter.default, 
                payload_codec=claim_check_codec
            )
            client_with_codec = Client(**new_config)
            
            task_queue = f"tq-logging-{uuid.uuid4()}"
            
            # Start worker with the codec
            async with Worker(
                client_with_codec,
                task_queue=task_queue,
                workflows=[ClaimCheckTestWorkflow],
                activities=[process_large_data, process_simple_data]
            ):
                # Execute workflow with large data
                await client_with_codec.execute_workflow(
                    ClaimCheckTestWorkflow.run,
                    large_test_data,
                    id=f"wf-logging-{uuid.uuid4()}",
                    task_queue=task_queue,
                )
                
                # Check that compression stats were logged
                log_text = caplog.text
                assert "Claim check encode:" in log_text
                assert "compression:" in log_text
                assert "%" in log_text
                
                # Should also see decode logs
                assert "Claim check decode:" in log_text
                assert "was compressed:" in log_text
                
        finally:
            await claim_check_codec.redis_client.aclose()

    @pytest.mark.asyncio
    async def test_codec_direct_functionality(self):
        """Test codec functionality directly (unit tests)."""
        # Test with compression enabled
        codec_compressed = ClaimCheckCodec(enable_compression=True)
        codec_uncompressed = ClaimCheckCodec(enable_compression=False)
        
        try:
            # Create test payload
            test_data = {"message": "Hello" * 1000, "numbers": list(range(100))}
            json_data = json.dumps(test_data).encode('utf-8')
            payload = Payload(
                metadata={"encoding": b"json/plain"},
                data=json_data
            )
            
            # Test compression enabled
            encoded_compressed = await codec_compressed.encode([payload])
            assert len(encoded_compressed) == 1
            assert encoded_compressed[0].metadata[b"temporal.io/claim-check-codec"] == b"v1c"
            
            # Test compression disabled
            encoded_uncompressed = await codec_uncompressed.encode([payload])
            assert len(encoded_uncompressed) == 1
            assert encoded_uncompressed[0].metadata[b"temporal.io/claim-check-codec"] == b"v1"
            
            # Test cross-compatibility: compressed codec can decode uncompressed
            decoded_by_compressed = await codec_compressed.decode(encoded_uncompressed)
            assert len(decoded_by_compressed) == 1
            assert decoded_by_compressed[0].data == payload.data
            
            # Test cross-compatibility: uncompressed codec can decode compressed
            decoded_by_uncompressed = await codec_uncompressed.decode(encoded_compressed)
            assert len(decoded_by_uncompressed) == 1
            assert decoded_by_uncompressed[0].data == payload.data
            
            # Test that compression actually reduces size
            claim_check_id = encoded_compressed[0].data.decode('utf-8')
            compressed_data = await codec_compressed.redis_client.get(claim_check_id)
            original_size = len(payload.SerializeToString())
            compressed_size = len(compressed_data)
            
            assert compressed_size < original_size
            compression_ratio = (1 - compressed_size / original_size) * 100
            assert compression_ratio > 10  # Should get some compression
            
        finally:
            await codec_compressed.redis_client.aclose()
            await codec_uncompressed.redis_client.aclose()

    @pytest.mark.asyncio
    async def test_non_claimcheck_passthrough(self):
        """Test that non-claim-check payloads pass through unchanged."""
        codec = ClaimCheckCodec(enable_compression=True)
        
        try:
            # Create a regular payload (not claim-checked)
            regular_payload = Payload(
                metadata={"encoding": b"json/plain"},
                data=b'{"test": "data"}'
            )
            
            # Decode should pass it through unchanged
            decoded_payloads = await codec.decode([regular_payload])
            
            assert len(decoded_payloads) == 1
            decoded = decoded_payloads[0]
            
            # Should be identical to input
            assert decoded.data == regular_payload.data
            assert decoded.metadata == regular_payload.metadata
            
        finally:
            await codec.redis_client.aclose()

    @pytest.mark.asyncio
    async def test_compression_threshold(self):
        """Test that compression is skipped for payloads below threshold."""
        # Create codec with 250 byte threshold
        codec = ClaimCheckCodec(enable_compression=True, compression_threshold=250)
        
        try:
            # Create small payload (below threshold)
            small_data = {"message": "small"}
            small_json = json.dumps(small_data).encode('utf-8')
            small_payload = Payload(
                metadata={"encoding": b"json/plain"},
                data=small_json
            )
            
            # Create large payload (above threshold)
            large_data = {"message": "large" * 100}  # Should be well above 250 bytes
            large_json = json.dumps(large_data).encode('utf-8')
            large_payload = Payload(
                metadata={"encoding": b"json/plain"},
                data=large_json
            )
            
            # Encode both payloads
            small_encoded = await codec.encode([small_payload])
            large_encoded = await codec.encode([large_payload])
            
            # Small payload should be v1 (uncompressed due to threshold)
            assert small_encoded[0].metadata[b"temporal.io/claim-check-codec"] == b"v1"
            
            # Large payload should be v1c (compressed)
            assert large_encoded[0].metadata[b"temporal.io/claim-check-codec"] == b"v1c"
            
            # Verify both can be decoded correctly
            small_decoded = await codec.decode(small_encoded)
            large_decoded = await codec.decode(large_encoded)
            
            assert small_decoded[0].data == small_payload.data
            assert large_decoded[0].data == large_payload.data
            
        finally:
            await codec.redis_client.aclose()

    @pytest.mark.asyncio
    async def test_custom_compression_threshold(self):
        """Test codec with custom compression threshold."""
        # Create codec with very low threshold (10 bytes)
        codec = ClaimCheckCodec(enable_compression=True, compression_threshold=10)
        
        try:
            # Create payload that's above 10 bytes but below 250 bytes
            medium_data = {"message": "medium size payload"}
            medium_json = json.dumps(medium_data).encode('utf-8')
            medium_payload = Payload(
                metadata={"encoding": b"json/plain"},
                data=medium_json
            )
            
            # This should be compressed since it's above 10 bytes
            encoded = await codec.encode([medium_payload])
            assert encoded[0].metadata[b"temporal.io/claim-check-codec"] == b"v1c"
            
            # Verify it can be decoded correctly
            decoded = await codec.decode(encoded)
            assert decoded[0].data == medium_payload.data
            
        finally:
            await codec.redis_client.aclose()


class TestClaimCheckPlugin:
    """Test suite for ClaimCheckPlugin configuration and integration."""

    @pytest.mark.asyncio
    async def test_plugin_disabled_by_default(self, client: Client, simple_test_data: SimpleTestData):
        """Test that plugin is disabled by default and doesn't affect workflows."""
        # Create plugin without setting environment variables (should be disabled)
        plugin = ClaimCheckPlugin()
        
        # Configure client with plugin
        new_config = client.config()
        new_config["data_converter"] = plugin.get_data_converter(new_config)
        client_with_plugin = Client(**new_config)
        
        task_queue = f"tq-plugin-disabled-{uuid.uuid4()}"
        
        # Start worker with the plugin
        async with Worker(
            client_with_plugin,
            task_queue=task_queue,
            workflows=[SimpleTestWorkflow]
        ):
            # Execute workflow - should work normally without claim check
            result = await client_with_plugin.execute_workflow(
                SimpleTestWorkflow.run,
                simple_test_data,
                id=f"wf-plugin-disabled-{uuid.uuid4()}",
                task_queue=task_queue,
            )
            
            # Verify the data is identical (no claim check processing)
            assert result.message == simple_test_data.message
            assert result.count == simple_test_data.count

    @pytest.mark.asyncio
    async def test_plugin_with_claim_check_enabled(self, client: Client, large_test_data: LargeTestData, monkeypatch):
        """Test plugin with claim check enabled via environment variables."""
        # Set environment variables to enable claim check
        monkeypatch.setenv("USE_CLAIM_CHECK", "True")
        monkeypatch.setenv("CLAIM_CHECK_COMPRESSION", "True")
        monkeypatch.setenv("CLAIM_CHECK_COMPRESSION_THRESHOLD", "100")
        monkeypatch.setenv("REDIS_HOST", "localhost")
        monkeypatch.setenv("REDIS_PORT", "6379")
        
        # Create plugin (should read the environment variables)
        plugin = ClaimCheckPlugin()
        
        # Verify plugin configuration
        assert plugin.useClaimCheck is True
        assert plugin.enableCompression is True
        assert plugin.compressionThreshold == 100
        assert plugin.redisHost == "localhost"
        assert plugin.redisPort == 6379
        
        # Configure client with plugin
        new_config = client.config()
        data_converter = plugin.get_data_converter(new_config)
        new_config["data_converter"] = data_converter
        client_with_plugin = Client(**new_config)
        
        task_queue = f"tq-plugin-enabled-{uuid.uuid4()}"
        
        # Start worker with the plugin
        async with Worker(
            client_with_plugin,
            task_queue=task_queue,
            workflows=[ClaimCheckTestWorkflow],
            activities=[process_large_data, process_simple_data]
        ):
            # Execute workflow with large data - should use claim check + compression
            result = await client_with_plugin.execute_workflow(
                ClaimCheckTestWorkflow.run,
                large_test_data,
                id=f"wf-plugin-enabled-{uuid.uuid4()}",
                task_queue=task_queue,
            )
            
            # Verify the result (data should have been processed through claim check)
            assert "Processed 100 items for user test-user-12345" in result
            assert "Message: test, Count: 42" in result
        
        # Clean up the codec's Redis connection
        if hasattr(data_converter, 'payload_codec') and data_converter.payload_codec:
            await data_converter.payload_codec.redis_client.aclose()

    @pytest.mark.asyncio
    async def test_plugin_environment_variable_parsing(self, monkeypatch):
        """Test that plugin correctly parses all environment variables."""
        # Test with various environment variable formats
        test_cases = [
            # (env_value, expected_bool)
            ("True", True),
            ("true", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("False", False),
            ("false", False),
            ("FALSE", False),
            ("0", False),
            ("no", False),
            ("", False),  # Empty string should be False
        ]
        
        for env_value, expected_bool in test_cases:
            # Test USE_CLAIM_CHECK parsing
            monkeypatch.setenv("USE_CLAIM_CHECK", env_value)
            monkeypatch.setenv("CLAIM_CHECK_COMPRESSION", "True")  # Keep other vars consistent
            
            plugin = ClaimCheckPlugin()
            assert plugin.useClaimCheck == expected_bool, f"Failed for USE_CLAIM_CHECK='{env_value}'"
            
            # Test CLAIM_CHECK_COMPRESSION parsing  
            monkeypatch.setenv("USE_CLAIM_CHECK", "True")
            monkeypatch.setenv("CLAIM_CHECK_COMPRESSION", env_value)
            
            plugin = ClaimCheckPlugin()
            assert plugin.enableCompression == expected_bool, f"Failed for CLAIM_CHECK_COMPRESSION='{env_value}'"

    @pytest.mark.asyncio
    async def test_plugin_default_values(self):
        """Test plugin default values when environment variables are not set."""
        import os
        
        # Temporarily remove environment variables if they exist
        env_vars_to_clear = [
            "USE_CLAIM_CHECK",
            "CLAIM_CHECK_COMPRESSION", 
            "CLAIM_CHECK_COMPRESSION_THRESHOLD",
            "REDIS_HOST",
            "REDIS_PORT"
        ]
        
        original_values = {}
        for var in env_vars_to_clear:
            original_values[var] = os.environ.get(var)
            if var in os.environ:
                del os.environ[var]
        
        try:
            # Create plugin with no environment variables set
            plugin = ClaimCheckPlugin()
            
            # Verify default values
            assert plugin.useClaimCheck is False  # Default should be False
            assert plugin.enableCompression is True  # Default should be True
            assert plugin.compressionThreshold == 250  # Default should be 250
            assert plugin.redisHost == "localhost"  # Default should be localhost
            assert plugin.redisPort == 6379  # Default should be 6379
            
        finally:
            # Restore original environment variables
            for var, value in original_values.items():
                if value is not None:
                    os.environ[var] = value
