# API to OpenAI Agents SDK + Temporal Workflow

Exposes a Temporal Workflow with an easy to use API

Operations
* 

## Prerequisites

* [uv](https://docs.astral.sh/uv/) - Python Package and Project Manager

## Set up Python Environment
```bash
uv sync
```

### Start API Server

#### Connect locally
```bash
uv run python -m src.temporal.api
```

#### Connect to Temporal Cloud
Configure your Temporal Cloud settings in the `.env` file. See [README](../README.md) for more details.
```bash
uv run python -m src.temporal.api
```

Test that the API is running:
```bash
curl http://127.0.0.1:8000
```

Start a workflow:
```bash
curl -X POST 'http://127.0.0.1:8000/start-workflow?workflow_id=<your-workflow-id>'
```

Send a prompt (first time)
```bash
curl -X POST 'http://127.0.0.1:8000/send-prompt?workflow_id=<your-workflow-id>&prompt=Who%20are%20my%20beneficiaries%3F&chat_len=0'
```

Respond with an account ID
```bash
curl -X POST 'http://127.0.0.1:8000/send-prompt?workflow_id=<your-workflow-id>&prompt=123&chat_len=1'
```

Ask about investment accounts
```bash
curl -X POST 'http://127.0.0.1:8000/send-prompt?workflow_id=<your-workflow-id>&prompt=What%20investment%20accounts%20do%20I%20have%3F&chat_len=2'
```

Query the chat history
```bash
curl "http://127.0.0.1:8000/get-chat-history?workflow_id=<your-workflow-id>&from_index=<index (integer)>"
```

End the Chat
```bash
curl -X POST "http://127.0.0.1:8000/end-chat?workflow_id=<your-workflow-id>"
```