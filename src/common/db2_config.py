"""
Shared DB2 Configuration Module

This module provides a centralized DB2 configuration class that automatically
loads connection parameters from environment variables. This eliminates the need
for manual os.getenv() calls throughout the codebase.

Environment Variables:
    DB2_HOST: Database hostname (default: localhost)
    DB2_PORT: Database port (default: 50000)
    DB2_DATABASE: Database name (default: testdb)
    DB2_USERNAME: Database username (default: db2inst1)
    DB2_PASSWORD: Database password (default: password)
    DB2_PROTOCOL: Connection protocol (default: TCPIP)

Example:
    # Automatically loads from environment variables
    config = DB2Config()
    
    # Or override with explicit values
    config = DB2Config(
        hostname="prod-db.example.com",
        port="50001",
        database="production"
    )
"""

import os
import logging
from dataclasses import dataclass
import ibm_db

logger = logging.getLogger(__name__)


@dataclass
class DB2Config:
    """
    Configuration for DB2 database connection.
    
    Automatically loads connection parameters from environment variables
    when instantiated with default values. Override by passing explicit values.
    """
    hostname: str = "localhost"
    port: str = "50000"
    database: str = "testdb"
    username: str = "db2inst1"
    password: str = "password"
    protocol: str = "TCPIP"

    def __post_init__(self):
        """Load configuration from environment variables if available."""
        self.hostname = os.getenv("DB2_HOST", self.hostname)
        self.port = os.getenv("DB2_PORT", self.port)
        self.database = os.getenv("DB2_DATABASE", self.database)
        self.username = os.getenv("DB2_USERNAME", self.username)
        self.password = os.getenv("DB2_PASSWORD", self.password)
        self.protocol = os.getenv("DB2_PROTOCOL", self.protocol)

    def get_connection_string(self) -> str:
        """
        Build DB2 connection string for ibm_db.
        
        Returns:
            Connection string in ibm_db format
        """
        return (
            f"DATABASE={self.database};"
            f"HOSTNAME={self.hostname};"
            f"PORT={self.port};"
            f"PROTOCOL={self.protocol};"
            f"UID={self.username};"
            f"PWD={self.password};"
        )


def create_claim_check_table(config: DB2Config = None) -> None:
    """
    Create the claim_check_payloads table if it doesn't exist.
    
    This table is used by the Temporal claim check codec to store large
    payloads outside of Temporal's history.
    
    Args:
        config: DB2 configuration (uses defaults if None)
        
    Raises:
        ConnectionError: If unable to connect to DB2
        Exception: If table creation fails
    """
    db2_config = config or DB2Config()
    conn = None
    
    try:
        conn_str = db2_config.get_connection_string()
        conn = ibm_db.connect(conn_str, "", "")
        
        if not conn:
            raise ConnectionError("Failed to establish DB2 connection")
        
        # Create claim check payloads table
        create_table_sql = """
            CREATE TABLE IF NOT EXISTS claim_check_payloads (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                payload_data CLOB NOT NULL,
                workflow_id VARCHAR(255) NOT NULL,
                workflow_run_id VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT TIMESTAMP,
                expires_at TIMESTAMP
            )
        """
        ibm_db.exec_immediate(conn, create_table_sql)
        
        # Create index for workflow cleanup
        create_index_workflow_sql = """
            CREATE INDEX IF NOT EXISTS idx_workflow_cleanup 
            ON claim_check_payloads (workflow_id, workflow_run_id)
        """
        try:
            ibm_db.exec_immediate(conn, create_index_workflow_sql)
        except Exception as e:
            # Index might already exist, log but don't fail
            logger.debug(f"Index creation skipped (may already exist): {e}")
        
        # Create index for expiration cleanup
        create_index_expires_sql = """
            CREATE INDEX IF NOT EXISTS idx_expires_at 
            ON claim_check_payloads (expires_at)
        """
        try:
            ibm_db.exec_immediate(conn, create_index_expires_sql)
        except Exception as e:
            # Index might already exist, log but don't fail
            logger.debug(f"Index creation skipped (may already exist): {e}")
        
        ibm_db.commit(conn)
        logger.info("Claim check table initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to create claim check table: {e}")
        if conn:
            ibm_db.rollback(conn)
        raise
        
    finally:
        if conn:
            ibm_db.close(conn)

