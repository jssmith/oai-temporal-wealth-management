# Wealth Management Agent Example using OpenAI Agents SDK
Demonstrates how to use OpenAI Agents SDK using handoffs to other agents with persistent conversation history using DB2Session.

The Temporal version of this example is located [here](../temporal/README.md) 

## Features

* **Persistent Conversation History**: Sessions are stored in DB2 and can be resumed across application restarts
* **REST API**: FastAPI server for programmatic access to agents
* **Session Management**: Create new sessions or resume existing ones by ID
* **Agent Handoffs**: Seamless transitions between specialized agents

## Scenarios currently implemented
* Add Beneficiary - add a new beneficiary to your account
* List Beneficiaries - shows a list of beneficiaries and their relationship to the account owner
* Delete Beneficiary - delete a beneficiary from your account
* Open Investment Account - opens a new investment account
* List Investments - shows a list of accounts and their current balances
* Close Investment Account - closes an investment account

## Prerequisites

* [uv](https://docs.astral.sh/uv/) - Python Package and Project Manager
* DB2 database (for persistent session storage)

## Set up Python Environment
```bash
uv sync
```

## Set up your Environment Variables

Create a `.env` file in the project root with your configuration:

```bash
cp .env.example .env
```

Now edit the `.env` file and add your configuration:
```text
# OpenAI Configuration
OPENAI_API_KEY=sk-proj-your-openai-api-key-here

# DB2 Configuration (for persistent sessions)
DB2_HOST=localhost
DB2_PORT=50000
DB2_DATABASE=testdb
DB2_USERNAME=db2inst1
DB2_PASSWORD=password
```

## Running the Application

### Option 1: Command Line Interface (Interactive)

Run the interactive command-line interface:
```bash
uv run python -m src.basic.cli
```

The application will prompt you to enter a conversation ID or create a new one. You can resume previous conversations by entering the same ID.

Example session:
```
Enter conversation ID (or press Enter for new conversation): 
Starting new conversation: a1b2c3d4e5f6g7h8
Welcome to ABC Wealth Management. How can I help you?
Enter your message: Who are my beneficiaries?
Supervisor Agent Could you please provide your client ID? This will help me assist you better.
Enter your message: 123
Supervisor Agent: Skipping item: HandoffCallItem
Handed off from Supervisor Agent to Beneficiary Agent
Beneficiary Agent: Calling a tool
Beneficiary Agent: Tool call output: [{'beneficiary_id': 'b-1b011a72', 'first_name': 'John', 'last_name': 'Doe', 'relationship': 'son'}]
Beneficiary Agent Here are your current beneficiaries:

1. **John Doe** - Son

Would you like to add or delete any beneficiaries, or do you need any more information?
Enter your message: end
Conversation a1b2c3d4e5f6g7h8 saved. You can resume it later by entering the same ID.
```

### Option 2: REST API Server

Start the FastAPI server for programmatic access:
```bash
uv run python -m src.basic.api
```

The API server will start on `http://localhost:8001` with the following endpoints:

#### API Endpoints

**Start a Workflow:**
```bash
curl -X POST "http://localhost:8001/start-workflow?workflow_id=your-workflow-id"
```

**Send a Message:**
```bash
curl -X POST "http://localhost:8001/send-prompt?workflow_id=your-workflow-id&prompt=Who%20are%20my%20beneficiaries%3F"
```

**Get Chat History:**
```bash
curl "http://localhost:8001/get-chat-history?workflow_id=your-workflow-id&from_index=0"
```

**End Chat:**
```bash
curl -X POST "http://localhost:8001/end-chat?workflow_id=your-workflow-id"
```

#### API Documentation

Once the server is running, visit `http://localhost:8001/docs` for interactive API documentation.

## Session Management

- **Persistent Storage**: All conversations are stored in DB2 and persist across application restarts
- **Session Resumption**: Use the same session ID to continue previous conversations
- **Session Isolation**: Each session ID maintains its own conversation history
- **Automatic Cleanup**: Sessions are automatically managed with timestamps

## Troubleshooting

### DB2 Connection Issues

If you see DB2 connection errors, ensure:
1. DB2 server is running and accessible
2. Database credentials in `.env` are correct
3. Database and tables exist (they will be created automatically on first connection)

### Without DB2

The application requires DB2 for session persistence. If DB2 is not available, sessions will not persist between application restarts, but the agents will still function for single-session interactions.