# Chat Flow Sequence Diagram

This document illustrates how chat interactions flow through the Temporal-based wealth management system.

## System Components

- **Client**: Frontend application or API consumer
- **API**: FastAPI server that handles HTTP requests
- **Temporal Server**: Orchestration engine managing workflows
- **Worker**: Python worker executing workflows and activities
- **OpenAI LLMs**: External AI service providing agent responses

## Complete Chat Flow

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Temporal Server
    participant Worker
    participant OpenAI LLMs

    %% START CHAT
    rect rgb(240, 248, 255)
    Note over Client,OpenAI LLMs: 1. Start Chat Session
    
    Client->>+API: POST /start-workflow?workflow_id=client-123
    API->>+Temporal Server: start_workflow(WealthManagementWorkflow)
    Temporal Server->>Temporal Server: Schedule workflow on task queue
    Temporal Server-->>-API: Workflow started
    API-->>-Client: {"message": "Workflow started"}
    
    Temporal Server->>+Worker: Assign workflow task
    Worker->>Worker: Initialize WealthManagementWorkflow
    Worker->>Worker: Initialize agent graph (supervisor, beneficiaries, investments)
    Worker->>Worker: Initialize DB2 session for conversation history
    Worker->>Worker: Enter run loop (wait for messages)
    Note over Worker: Workflow running, waiting for requests
    end

    %% SEND MESSAGE
    rect rgb(240, 255, 240)
    Note over Client,OpenAI LLMs: 2. Send Message and Receive Response
    
    Client->>+API: POST /send-prompt?workflow_id=client-123&prompt=List my beneficiaries
    API->>+Temporal Server: execute_update(process_user_message)
    Note over API,Temporal Server: Synchronous update - waits for response
    
    Temporal Server->>+Worker: Deliver update to workflow
    Worker->>Worker: Update handler: Queue message in WorkflowRequestService
    Worker->>Worker: Run loop: Pick up request from queue
    Worker->>Worker: Call _process_user_message_request()
    
    Worker->>+OpenAI LLMs: Runner.run(agent, message, context, session)
    Note over Worker,OpenAI LLMs: Session auto-loads conversation history from DB2
    OpenAI LLMs->>OpenAI LLMs: Process message with agent instructions
    OpenAI LLMs->>OpenAI LLMs: Determine if tool calls needed
    OpenAI LLMs-->>-Worker: Agent response (may include tool calls)
    
    opt Tool Calls Required
        Worker->>Worker: Execute activity tools (e.g., list_beneficiaries)
        Worker->>+OpenAI LLMs: Send tool results back to LLM
        OpenAI LLMs->>OpenAI LLMs: Process tool results
        OpenAI LLMs-->>-Worker: Final response with results
    end
    
    Worker->>Worker: Extract text_response, json_response, agent_trace
    Worker->>Worker: Session auto-saves message to DB2
    Worker->>Worker: Complete request with ChatInteraction
    Worker-->>-Temporal Server: Return ProcessUserMessageResponse
    
    Temporal Server-->>-API: Update result with chat interaction
    API-->>-Client: {"success": true, "chat_interaction": {...}}
    end

    %% END CHAT
    rect rgb(255, 248, 240)
    Note over Client,OpenAI LLMs: 3. End Chat Session
    
    Client->>+API: POST /end-chat?workflow_id=client-123
    API->>+Temporal Server: signal("end_workflow")
    Temporal Server-->>-API: Signal sent
    API-->>-Client: {"message": "End chat signal sent"}
    
    Temporal Server->>+Worker: Deliver signal to workflow
    Worker->>Worker: Set end_workflow flag = True
    Worker->>Worker: Run loop detects end_workflow
    Worker->>Worker: Execute cleanup (claim check, close resources)
    Worker->>Worker: Exit run loop
    Worker-->>-Temporal Server: Workflow completed
    Note over Worker: Workflow terminated
    end
```

## Flow Details

### 1. Start Chat Session

**Endpoint**: `POST /start-workflow`

The workflow is started and enters a loop waiting for user messages:

1. Client sends request to start a new workflow with a unique workflow ID
2. API calls Temporal's `start_workflow()` to initiate the workflow
3. Temporal Server schedules the workflow execution on a task queue
4. Worker picks up the workflow task and:
   - Initializes the `WealthManagementWorkflow` instance
   - Creates the agent graph (supervisor, beneficiaries, investments agents)
   - Initializes a DB2 session for persistent conversation history
   - Enters the main run loop, waiting for messages or signals

### 2. Send Message and Receive Response

**Endpoint**: `POST /send-prompt`

The message is processed synchronously using Temporal's update mechanism:

1. Client sends a message prompt to the API
2. API calls `execute_update(process_user_message)` - a **synchronous operation** that waits for the response
3. Temporal Server delivers the update to the running workflow
4. Worker's update handler:
   - Queues the message in `WorkflowRequestService`
   - Main run loop picks up the request
   - Calls `_process_user_message_request()` which invokes `Runner.run()`
5. Worker communicates with OpenAI LLMs:
   - Session automatically loads conversation history from DB2
   - LLM processes the message with agent context
   - If tool calls are needed (e.g., listing beneficiaries), the worker executes activities and sends results back to the LLM
   - LLM generates final response
6. Worker processes the result:
   - Extracts text response, JSON data, and agent trace
   - Session automatically saves the interaction to DB2
   - Completes the request with a `ChatInteraction` object
7. Response flows back: Worker → Temporal Server → API → Client

### 3. End Chat Session

**Endpoint**: `POST /end-chat`

The workflow is gracefully terminated using a signal:

1. Client requests to end the chat session
2. API sends an `end_workflow` signal via Temporal
3. Temporal Server delivers the signal to the workflow
4. Worker sets the `end_workflow` flag to `True`
5. Main run loop detects the flag and:
   - Performs cleanup operations (claim check payloads, resources)
   - Exits the run loop
   - Workflow completes and terminates

## Key Architectural Features

### Synchronous Updates
The `execute_update()` mechanism ensures that each message gets a response before the next message is processed, maintaining conversation order and state consistency.

### Persistent Conversation History
The DB2 session automatically manages conversation history:
- Loads previous messages when `Runner.run()` is called
- Saves new interactions after each response
- Persists across workflow continue-as-new operations

### Agent Graph
Multiple specialized agents handle different domains:
- **Supervisor Agent**: Routes requests to appropriate specialized agents
- **Beneficiaries Agent**: Manages beneficiary operations
- **Investments Agent**: Handles investment accounts
- **Open Account Agent**: Manages account opening workflows

### Tool Execution
Agents can call activities as tools:
- `list_beneficiaries`, `add_beneficiary`, `delete_beneficiary`
- `list_investments`, `open_investment`, `close_investment`
- Tool results are sent back to the LLM for final response generation

## Implementation References

- **API Server**: `src/temporal/api/main.py`
- **Worker**: `src/temporal/run_worker.py`
- **Workflow**: `src/temporal/workflows/supervisor_workflow.py`
- **Request Service**: `src/temporal/services/workflow_request_service.py`
- **Session Management**: `src/temporal/session/temporal_db2_session.py`

