"""
FastAPI server for basic implementation with DB2Session-based chat history.

Provides REST API endpoints for creating chats, sending messages, and retrieving history.
"""

import asyncio
import uuid
import logging
import os
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from agents import (
    Agent,
    HandoffOutputItem,
    ItemHelpers,
    MessageOutputItem,
    RunContextWrapper,
    Runner,
    ToolCallItem,
    ToolCallOutputItem,
    TResponseInputItem,
    function_tool,
    trace,
)

from common.account_context import ClientContext
from common.agent_constants import BENE_AGENT_NAME, BENE_HANDOFF, BENE_INSTRUCTIONS, INVEST_AGENT_NAME, INVEST_HANDOFF, \
    INVEST_INSTRUCTIONS, SUPERVISOR_AGENT_NAME, SUPERVISOR_HANDOFF, SUPERVISOR_INSTRUCTIONS
from common.beneficiaries_manager import BeneficiariesManager
from common.investment_manager import InvestmentManager

# Import DB2Session for persistent conversation history
from common.db2_session import DB2Session
from common.db2_config import DB2Config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize managers
investment_acct_mgr = InvestmentManager()
beneficiaries_mgr = BeneficiariesManager()

# Tools (same as in main.py)
@function_tool
async def add_beneficiaries(
        context: RunContextWrapper[ClientContext], client_id: str,
        first_name: str, last_name: str, relationship: str
):
    context.context.client_id = client_id
    beneficiaries_mgr.add_beneficiary(client_id, first_name, last_name, relationship)

@function_tool
async def list_beneficiaries(
        context: RunContextWrapper[ClientContext], client_id: str
) -> list:
    """
    List the beneficiaries for the given client id.

    Args:
        client_id: The customer's client id
    """
    context.context.client_id = client_id
    return beneficiaries_mgr.list_beneficiaries(client_id)

@function_tool
async def delete_beneficiaries(
        context: RunContextWrapper[ClientContext], client_id: str, beneficiary_id: str
):
        context.context.client_id = client_id
        logger.info(f"Tool: Deleting beneficiary {beneficiary_id} from account {client_id}")
        beneficiaries_mgr.delete_beneficiary(client_id, beneficiary_id)

@function_tool
async def open_investment(context: RunContextWrapper[ClientContext], client_id: str, name: str, balance: str):
    context.context.client_id = client_id
    investment_acct_mgr.add_investment_account(client_id, name, balance)

@function_tool
async def list_investments(
        context: RunContextWrapper[ClientContext], client_id: str
) -> dict:
    """
    List the investment accounts and balances for the given client id.

    Args:
        client_id: The customer's client id'
    """
    context.context.client_id = client_id
    return investment_acct_mgr.list_investment_accounts(client_id)

@function_tool
async def close_investment(context: RunContextWrapper[ClientContext], client_id: str, investment_id: str):
    context.context.client_id = client_id
    investment_acct_mgr.delete_investment_account(client_id, investment_id)

# Initialize agents (same as in main.py)
beneficiary_agent = Agent[ClientContext](
    name=BENE_AGENT_NAME,
    handoff_description=BENE_HANDOFF,
    instructions=BENE_INSTRUCTIONS,
    tools=[list_beneficiaries, add_beneficiaries, delete_beneficiaries],
)

investment_agent = Agent[ClientContext](
    name=INVEST_AGENT_NAME,
    handoff_description=INVEST_HANDOFF,
    instructions=INVEST_INSTRUCTIONS,
    tools=[list_investments, open_investment, close_investment],
)

supervisor_agent = Agent[ClientContext](
    name=SUPERVISOR_AGENT_NAME,
    handoff_description=SUPERVISOR_HANDOFF,
    instructions=SUPERVISOR_INSTRUCTIONS,
    handoffs=[
        beneficiary_agent,
        investment_agent,
    ]
)

beneficiary_agent.handoffs.append(supervisor_agent)
investment_agent.handoffs.append(supervisor_agent)

# Global DB2 configuration
# DB2 configuration - automatically loads from environment variables
db2_config = DB2Config()

# Pydantic models for API - Updated to match Temporal API format
class ChatInteraction(BaseModel):
    user_prompt: str
    text_response: str
    json_response: str = ""
    agent_trace: str = ""

class SendPromptResponse(BaseModel):
    success: bool
    chat_interaction: ChatInteraction
    error_message: Optional[str] = None

class StartWorkflowResponse(BaseModel):
    message: str

# FastAPI app
app = FastAPI(
    title="Basic Agents API",
    description="OpenAI Agents SDK with DB2 Session Management",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "Basic Agents API with DB2 Session Management"}

@app.post("/start-workflow", response_model=StartWorkflowResponse)
async def start_workflow(workflow_id: str):
    """Start a new workflow session"""
    try:
        # Initialize session to ensure it exists
        session = DB2Session(session_id=workflow_id, config=db2_config)
        
        try:
            # Check if session has existing messages using sync method
            existing_items = session.get_items_sync()
            
            message = "Workflow started."
            if existing_items and len(existing_items) > 0:
                message = f"Workflow resumed with {len(existing_items)} existing messages."
            
            return StartWorkflowResponse(message=message)
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Error starting workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {str(e)}")

@app.post("/send-prompt", response_model=SendPromptResponse)
async def send_prompt(workflow_id: str, prompt: str):
    """Send a prompt to a workflow and get the agent's response"""
    try:
        # Initialize session
        session = DB2Session(session_id=workflow_id, config=db2_config)
        
        try:
            # Initialize context and agent
            context = ClientContext()
            current_agent = supervisor_agent
            
            # Run the agent with the session-managed conversation history
            # The session automatically handles adding user messages and conversation history
            with trace("wealth management api", group_id=workflow_id):
                result = await Runner.run(
                    current_agent, 
                    prompt,
                    session=session,
                    context=context)
            
            # Extract the response from the result
            response_text = ""
            agent_name = "Unknown"
            
            for new_item in result.new_items:
                agent_name = new_item.agent.name
                if isinstance(new_item, MessageOutputItem):
                    response_text = ItemHelpers.text_message_output(new_item)
                    break
            
            if not response_text:
                response_text = "I received your message but couldn't generate a response."
            
            return SendPromptResponse(
                success=True,
                chat_interaction=ChatInteraction(
                    user_prompt=prompt,
                    text_response=response_text,
                    json_response="",
                    agent_trace=agent_name
                )
            )
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Error sending prompt: {e}")
        return SendPromptResponse(
            success=False,
            chat_interaction=ChatInteraction(
                user_prompt=prompt,
                text_response="Sorry, there was an error processing your request.",
                json_response="",
                agent_trace=f"Error: {e}"
            ),
            error_message=str(e)
        )

@app.post("/end-chat")
async def end_chat(workflow_id: str):
    """End a chat workflow"""
    try:
        # For the OAI supervisor, we don't need to do anything special to end the chat
        # The session will persist and can be resumed later
        return {"message": "End chat signal sent."}
    except Exception as e:
        logger.error(f"Error ending chat: {e}")
        return {"message": f"Error ending chat: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
