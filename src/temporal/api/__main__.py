"""Uvicorn runner for temporal API."""
import uvicorn
import logging

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    # Configure custom logging format
    log_format = "%(asctime)s | %(levelname)s | %(filename)s:%(lineno)s | %(message)s"
    logging.basicConfig(level=logging.INFO, format=log_format)
    
    # Configure uvicorn's loggers to use the same format
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers = []  # Remove default handlers
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(log_format))
        uvicorn_logger.addHandler(handler)
        uvicorn_logger.propagate = False
    
    uvicorn.run("src.temporal.api.main:app", host="0.0.0.0", port=8000, reload=True)

