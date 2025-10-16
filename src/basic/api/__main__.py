"""Uvicorn runner for basic API."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.basic.api.main:app", host="0.0.0.0", port=8001, reload=True)
