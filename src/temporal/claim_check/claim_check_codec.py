import uuid
import base64
import logging
import ibm_db
from typing import Iterable, List, Optional
from datetime import datetime, timedelta

from temporalio.api.common.v1 import Payload
from temporalio.converter import PayloadCodec
from temporalio import workflow

from src.common.db2_config import DB2Config, create_claim_check_table

logger = logging.getLogger(__name__)

#
# Substitutes the payload for a GUID
# and stores the original payload in DB2 using ibm_db
# Supports workflow-based cleanup when workflows complete
#
class ClaimCheckCodec(PayloadCodec):

    def __init__(self, config: Optional[DB2Config] = None, ttl_hours: int = 24):
        """
        Initialize ClaimCheckCodec with DB2 storage.
        
        Args:
            config: DB2 configuration (uses defaults if None)
            ttl_hours: Time-to-live for payloads in hours (default 24)
        """
        self.config = config or DB2Config()
        self.ttl_hours = ttl_hours
        self._connection = None
        self._initialized = False
        
    def _get_connection(self):
        """Get or create DB2 connection."""
        if self._connection is None:
            try:
                conn_str = self.config.get_connection_string()
                self._connection = ibm_db.connect(conn_str, "", "")
                if not self._connection:
                    raise ConnectionError("Failed to establish DB2 connection")
                
                # Initialize database schema on first connection
                if not self._initialized:
                    create_claim_check_table(self.config)
                    self._initialized = True
                    
                logger.debug("Established DB2 connection for claim check codec")
                
            except Exception as e:
                logger.error(f"Failed to connect to DB2: {e}")
                raise ConnectionError(f"DB2 connection failed: {e}")
                
        return self._connection
    async def encode(self, payloads: Iterable[Payload]) -> List[Payload]:
        out: list[Payload] = []
        for p in payloads:
            encoded = await self.encode_payload(p)
            out.append(encoded)

        return out

    async def decode(self, payloads: Iterable[Payload]) -> List[Payload]:
        out: List[Payload] = []
        for p in payloads:
            if p.metadata.get("temporal.io/claim-check-codec", b"").decode() != "v1":
                out.append(p)
                continue

            payload_id = p.data.decode("utf-8")
            try:
                conn = self._get_connection()
                
                # Query for the claim check payload
                query_sql = """
                    SELECT payload_data 
                    FROM claim_check_payloads 
                    WHERE id = ?
                """
                stmt = ibm_db.prepare(conn, query_sql)
                ibm_db.bind_param(stmt, 1, payload_id)
                ibm_db.execute(stmt)
                
                result = ibm_db.fetch_tuple(stmt)
                
                if result:
                    # Decode the base64 encoded payload data
                    payload_data = result[0]
                    payload_bytes = base64.b64decode(payload_data)
                    new_payload = Payload.FromString(payload_bytes)
                    out.append(new_payload)
                else:
                    logger.error(f"Claim check payload not found: {payload_id}")
                    # Return original payload if not found
                    out.append(p)
                    
            except Exception as e:
                logger.error(f"Failed to decode claim check payload {payload_id}: {e}")
                # Return original payload on error
                out.append(p)
                
        return out

    async def encode_payload(self, payload: Payload) -> Payload:
        payload_id = str(uuid.uuid4())
        payload_bytes = payload.SerializeToString()
        
        # Get workflow context for tracking
        workflow_id = None
        workflow_run_id = None
        try:
            if workflow.in_workflow():
                info = workflow.info()
                workflow_id = info.workflow_id
                workflow_run_id = info.run_id
        except Exception:
            # Not in workflow context, that's okay
            pass
        
        # Calculate expiration time
        expires_at = datetime.utcnow() + timedelta(hours=self.ttl_hours)
        expires_at_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')
        
        try:
            conn = self._get_connection()
            
            # Base64 encode the payload data for storage
            encoded_data = base64.b64encode(payload_bytes).decode('utf-8')
            
            # Insert claim check payload
            insert_sql = """
                INSERT INTO claim_check_payloads 
                (id, payload_data, workflow_id, workflow_run_id, expires_at)
                VALUES (?, ?, ?, ?, ?)
            """
            stmt = ibm_db.prepare(conn, insert_sql)
            ibm_db.bind_param(stmt, 1, payload_id)
            ibm_db.bind_param(stmt, 2, encoded_data)
            ibm_db.bind_param(stmt, 3, workflow_id or "unknown")
            ibm_db.bind_param(stmt, 4, workflow_run_id or "")
            ibm_db.bind_param(stmt, 5, expires_at_str)
            ibm_db.execute(stmt)
            ibm_db.commit(conn)
            
            logger.debug(f"Stored claim check payload {payload_id} for workflow {workflow_id}")
            
        except Exception as e:
            logger.error(f"Failed to store claim check payload {payload_id}: {e}")
            if conn:
                ibm_db.rollback(conn)
            raise
        
        out = Payload(
            metadata={
                "encoding": b"claim-checked",
                "temporal.io/claim-check-codec": b"v1",
            },
            data=payload_id.encode("utf-8"),
        )
        return out
    
    async def cleanup_workflow_payloads(self, workflow_id: str, workflow_run_id: Optional[str] = None):
        """
        Clean up claim check payloads for a completed workflow.
        
        Args:
            workflow_id: The workflow ID to clean up
            workflow_run_id: Optional workflow run ID for more specific cleanup
        """
        try:
            conn = self._get_connection()
            
            if workflow_run_id:
                delete_sql = """
                    DELETE FROM claim_check_payloads 
                    WHERE workflow_id = ? AND workflow_run_id = ?
                """
                stmt = ibm_db.prepare(conn, delete_sql)
                ibm_db.bind_param(stmt, 1, workflow_id)
                ibm_db.bind_param(stmt, 2, workflow_run_id)
            else:
                delete_sql = """
                    DELETE FROM claim_check_payloads 
                    WHERE workflow_id = ?
                """
                stmt = ibm_db.prepare(conn, delete_sql)
                ibm_db.bind_param(stmt, 1, workflow_id)
            
            ibm_db.execute(stmt)
            deleted_count = ibm_db.num_rows(stmt)
            ibm_db.commit(conn)
            
            logger.info(f"Cleaned up {deleted_count} claim check payloads for workflow {workflow_id}")
            
        except Exception as e:
            logger.error(f"Failed to cleanup payloads for workflow {workflow_id}: {e}")
            if conn:
                ibm_db.rollback(conn)
    
    async def cleanup_expired_payloads(self):
        """Clean up expired claim check payloads."""
        try:
            conn = self._get_connection()
            
            now = datetime.utcnow()
            now_str = now.strftime('%Y-%m-%d %H:%M:%S')
            
            delete_sql = """
                DELETE FROM claim_check_payloads 
                WHERE expires_at < ?
            """
            stmt = ibm_db.prepare(conn, delete_sql)
            ibm_db.bind_param(stmt, 1, now_str)
            ibm_db.execute(stmt)
            deleted_count = ibm_db.num_rows(stmt)
            ibm_db.commit(conn)
            
            logger.info(f"Cleaned up {deleted_count} expired claim check payloads")
            
        except Exception as e:
            logger.error(f"Failed to cleanup expired payloads: {e}")
            if conn:
                ibm_db.rollback(conn)
    
    def close(self):
        """Close database connections."""
        try:
            if self._connection:
                ibm_db.close(self._connection)
                self._connection = None
                logger.debug("Closed DB2 connection for claim check codec")
        except Exception as e:
            logger.error(f"Error closing DB2 connection: {e}")
