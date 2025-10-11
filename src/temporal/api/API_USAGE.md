# Temporal API Usage Guide

## Overview

The Temporal API provides endpoints for managing wealth management workflows with support for agent-based conversation, continue-as-new functionality, and persistent conversation history.

## Endpoints

### Start Workflow

**Endpoint:** `POST /start-workflow`

**Query Parameters:**
- `workflow_id` (required): Unique identifier for the workflow

**Description:** Starts a new wealth management workflow. The workflow will persist conversation history in DB2 and can be resumed across continue-as-new operations.

**Configuration:** Continue-as-new mode is controlled by the `FORCE_CONTINUE_AS_NEW` environment variable:
- `FORCE_CONTINUE_AS_NEW=true` - Test mode: always trigger continue-as-new after each message
- `FORCE_CONTINUE_AS_NEW=false` - Production mode: only when history gets large (default)

**Examples:**

```bash
# Start a workflow (mode controlled by environment variable)
curl -X POST "http://localhost:8000/start-workflow?workflow_id=client-12345"
```

**Response:**
```json
{
  "message": "Workflow started with force_continue_as_new=false."
}
```

### Send Message

**Endpoint:** `POST /send-prompt`

**Query Parameters:**
- `workflow_id` (required): Workflow identifier
- `prompt` (required): User's message to the agent

**Description:** Sends a message to the workflow and waits for the agent's response. Messages are processed serially in the workflow's main loop.

**Examples:**

```bash
# Send a message about beneficiaries
curl -X POST "http://localhost:8000/send-prompt?workflow_id=client-12345&prompt=List%20my%20beneficiaries"

# Send a message about investments
curl -X POST "http://localhost:8000/send-prompt?workflow_id=client-12345&prompt=What%20are%20my%20investment%20balances?"
```

**Response:**
```json
{
  "success": true,
  "chat_interaction": {
    "user_prompt": "List my beneficiaries",
    "text_response": "Here are your beneficiaries for client client-12345:\n...",
    "json_response": "",
    "agent_trace": "Supervisor Agent: Calling a tool\n..."
  },
  "error_message": null
}
```

### End Chat

**Endpoint:** `POST /end-chat`

**Query Parameters:**
- `workflow_id` (required): Workflow identifier

**Description:** Signals the workflow to clean up and terminate gracefully.

**Examples:**

```bash
curl -X POST "http://localhost:8000/end-chat?workflow_id=client-12345"
```

**Response:**
```json
{
  "message": "End chat signal sent."
}
```

## Continue-as-New Behavior

Controlled by the `FORCE_CONTINUE_AS_NEW` environment variable (set before starting the API).

### Production Mode (`FORCE_CONTINUE_AS_NEW=false` or unset)

The workflow uses Temporal's built-in suggestion for continue-as-new, which triggers when:
- Workflow history size reaches a threshold (~10K events)
- Workflow has been running for an extended period

**Use Case:** Production environments with natural conversation flows

**Setup:**
```bash
# In .env file
FORCE_CONTINUE_AS_NEW=false

# Or leave unset (false is default)
# Then start API
uv run python -m src.temporal.api
```

### Test Mode (`FORCE_CONTINUE_AS_NEW=true`)

The workflow triggers continue-as-new after processing each message.

**Use Case:** 
- Testing continue-as-new functionality
- Verifying state preservation
- Development and debugging

**Setup:**
```bash
# In .env file or export
export FORCE_CONTINUE_AS_NEW=true

# Then start API
uv run python -m src.temporal.api
```

## State Preservation

### Preserved Across Continue-as-New

✅ **Current Agent**: Which agent is active (Supervisor, Beneficiaries, Investments)
✅ **Context**: Client ID and other context variables
✅ **Configuration**: Run config and settings

### Restored from DB2

🔄 **Conversation History**: All previous chat interactions
🔄 **Input Items**: LLM conversation context

## Request Processing

### Request Flow

1. **Client** sends message via `/send-prompt`
2. **Update Handler** queues request in `WorkflowRequestService`
3. **Run Loop** retrieves request from queue
4. **Agent** processes message with full conversation context
5. **Run Loop** completes request with response
6. **Update Handler** returns response to client

### Benefits

- ✅ **Serial Processing**: Messages processed one at a time, maintaining conversation order
- ✅ **State Consistency**: Agent state updated atomically per message
- ✅ **Error Handling**: Centralized error handling in run loop
- ✅ **Continue-as-New**: Safe continuation points between messages

## Example Workflows

### Basic Conversation

```bash
# 1. Start workflow
curl -X POST "http://localhost:8000/start-workflow?workflow_id=user-001"

# 2. Ask about beneficiaries
curl -X POST "http://localhost:8000/send-prompt?workflow_id=user-001&prompt=Who%20are%20my%20beneficiaries?"

# 3. Add a beneficiary
curl -X POST "http://localhost:8000/send-prompt?workflow_id=user-001&prompt=Add%20John%20Doe%20as%20a%20beneficiary%2C%20relationship%20is%20spouse"

# 4. Check investments
curl -X POST "http://localhost:8000/send-prompt?workflow_id=user-001&prompt=What%20are%20my%20investment%20balances?"

# 5. End conversation
curl -X POST "http://localhost:8000/end-chat?workflow_id=user-001"
```

### Testing Continue-as-New

```bash
# 1. Start in test mode
curl -X POST "http://localhost:8000/start-workflow?workflow_id=test-can-001&force_continue_as_new=true"

# 2. Send first message (will trigger continue-as-new)
curl -X POST "http://localhost:8000/send-prompt?workflow_id=test-can-001&prompt=List%20beneficiaries%20for%20client123"

# 3. Send second message (verify state preserved after continuation)
curl -X POST "http://localhost:8000/send-prompt?workflow_id=test-can-001&prompt=What%20is%20my%20client%20ID?"

# 4. Check Temporal UI to see multiple workflow runs with same workflow_id
# Each run should show preserved agent state and context

# 5. End test
curl -X POST "http://localhost:8000/end-chat?workflow_id=test-can-001"
```

### Multi-Agent Handoff

```bash
# 1. Start workflow
curl -X POST "http://localhost:8000/start-workflow?workflow_id=user-002"

# 2. Ask general question (Supervisor handles)
curl -X POST "http://localhost:8000/send-prompt?workflow_id=user-002&prompt=What%20can%20you%20help%20me%20with?"

# 3. Ask about investments (hands off to Investment Agent)
curl -X POST "http://localhost:8000/send-prompt?workflow_id=user-002&prompt=List%20my%20investment%20accounts"

# 4. Open new account (Investment Agent → Open Account Agent)
curl -X POST "http://localhost:8000/send-prompt?workflow_id=user-002&prompt=Open%20a%20new%20retirement%20account"

# 5. Switch to beneficiaries (hands off to Beneficiaries Agent)
curl -X POST "http://localhost:8000/send-prompt?workflow_id=user-002&prompt=List%20my%20beneficiaries"
```

## Monitoring

### Temporal UI

View workflow execution details at: `http://localhost:8233`

**What to Check:**
- Workflow execution history
- Continue-as-new transitions (multiple runs for same workflow_id)
- Agent tool calls in event history
- Update handler responses

### Logs

Worker logs show detailed execution flow:

```
INFO: Update handler: Queueing user message: List my beneficiaries
INFO: Waiting for next request from queue
INFO: Got request: List my beneficiaries
INFO: Processing request: List my beneficiaries
INFO: Runner.run has exited.
INFO: Request completed successfully
INFO: Update handler: Received response for message
```

## Error Handling

### Guardrail Blocks

If a user asks non-wealth-management questions:

```json
{
  "success": true,
  "chat_interaction": {
    "user_prompt": "What's the weather today?",
    "text_response": "I'm sorry, but I can only help with wealth management questions...",
    "agent_trace": "Guardrail blocked non-wealth-management question"
  }
}
```

### Processing Errors

If an error occurs during message processing:

```json
{
  "success": false,
  "chat_interaction": {
    "user_prompt": "Invalid request",
    "text_response": "I'm sorry, there was an error processing your message...",
    "agent_trace": "Error: <error details>"
  },
  "error_message": "Detailed error message"
}
```

## Best Practices

1. **Workflow IDs**: Use meaningful, unique identifiers (e.g., `client-{client_id}`, `user-{user_id}`)
2. **Testing**: Use `force_continue_as_new=true` for testing, `false` for production
3. **Error Handling**: Check `success` field in response before processing results
4. **Cleanup**: Always call `/end-chat` when conversation is complete
5. **Monitoring**: Monitor Temporal UI for workflow health and history size

## Troubleshooting

### Workflow Not Starting

- Ensure Temporal server is running: `temporal server start-dev`
- Ensure worker is running: `uv run python -m src.temporal.run_worker`
- Check worker logs for errors

### Messages Not Processing

- Check workflow is still running in Temporal UI
- Verify DB2 is accessible
- Check worker logs for exceptions

### Continue-as-New Not Triggering

- Normal mode: History must reach threshold (~10K events)
- Test mode: Ensure `force_continue_as_new=true` was set on workflow start
- Check Temporal UI for multiple runs with same workflow_id

## Configuration

### Environment Variables

Required in `.env`:

```bash
# OpenAI
OPENAI_API_KEY=sk-...

# Temporal
TEMPORAL_ADDRESS=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=wealth-management-queue

# DB2 (for conversation history)
DB2_HOST=localhost
DB2_PORT=50000
DB2_DATABASE=testdb
DB2_USERNAME=db2inst1
DB2_PASSWORD=password
```

### API Port

Default: `8000`

Change in `src/temporal/api/__main__.py`:

```python
uvicorn.run(app, host="0.0.0.0", port=8000)
```

