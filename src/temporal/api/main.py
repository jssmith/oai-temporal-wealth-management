from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator
import os
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import TemporalError
from temporalio.contrib.openai_agents import OpenAIAgentsPlugin
from temporalio.service import RPCError

import logging
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

from common.client_helper import ClientHelper
from common.user_message import ProcessUserMessageInput
from src.temporal.claim_check.claim_check_plugin import ClaimCheckPlugin
from src.temporal.workflows.supervisor_workflow import WealthManagementWorkflow

temporal_client: Optional[Client] = None
task_queue: Optional[str] = None

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # app startup
    print("API is starting up...")
    global temporal_client
    global task_queue
    client_helper = ClientHelper()
    task_queue = client_helper.taskQueue
    temporal_client = await Client.connect(
        target_host=client_helper.address,
        namespace=client_helper.namespace,
        tls=client_helper.get_tls_config(),
        plugins=[
            OpenAIAgentsPlugin(),
            ClaimCheckPlugin(),
        ]
    )
    yield
    print("API is shutting down...")
    # app teardown
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "OpenAI Agent SDK + Temporal Agent!"}

@app.post("/send-prompt")
async def send_prompt(workflow_id: str, prompt: str):
    print(f"Received prompt {prompt}")

    message = ProcessUserMessageInput(
        user_input = prompt,
    )

    try:
        handle = temporal_client.get_workflow_handle(workflow_id=workflow_id)
        # Use update instead of signal to get immediate response
        result = await handle.execute_update(
            WealthManagementWorkflow.process_user_message,
            args=[message]
        )
        print(f"Received response: {result}")
        
        # Return the chat interaction directly
        return {
            "success": result.success,
            "chat_interaction": {
                "user_prompt": result.chat_interaction.user_prompt,
                "text_response": result.chat_interaction.text_response,
                "json_response": result.chat_interaction.json_response,
                "agent_trace": result.chat_interaction.agent_trace
            },
            "error_message": result.error_message
        }
    except RPCError as e:
        print(f"RPC Error: {e}")
        return {
            "success": False,
            "error_message": f"RPC Error: {e}",
            "chat_interaction": {
                "user_prompt": prompt,
                "text_response": "Sorry, there was an error processing your request.",
                "json_response": "",
                "agent_trace": f"RPC Error: {e}"
            }
        }
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {
            "success": False,
            "error_message": f"Unexpected error: {e}",
            "chat_interaction": {
                "user_prompt": prompt,
                "text_response": "Sorry, there was an unexpected error.",
                "json_response": "",
                "agent_trace": f"Error: {e}"
            }
        }


@app.post("/end-chat")
async def end_chat(workflow_id: str):
    """Sends an end_workflow signal to the workflow."""
    try:
        handle = temporal_client.get_workflow_handle(workflow_id=workflow_id)
        await handle.signal("end_workflow")
        return {"message": "End chat signal sent."}
    except TemporalError as e:
        logger.error(f"Error sending end chat signal: {e}")
        #print(e)
        # Workflow not found; return an empty response
        return {}

UPDATE_STATUS_NAME = "update_status"

@app.post("/start-workflow")
async def start_workflow(workflow_id: str):
    """
    Start a new workflow.
    
    Args:
        workflow_id: Unique identifier for the workflow
    
    """
    logger.info(f"Starting workflow {workflow_id}")
    print(f"Starting workflow {workflow_id}")
    try:
        # start the workflow with parameters
        # args are passed to the run() method in order: current_agent_name, context
        # force_continue_as_new is read from environment variable in the workflow module
        await temporal_client.start_workflow(
            WealthManagementWorkflow.run,
            args=[None, None],  # current_agent_name=None, context=None
            id=workflow_id,
            task_queue=task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE
        )
        logger.info(f"Workflow completed {workflow_id}")
        print(f"Workflow completed {workflow_id}")
        return {
            "message": f"Workflow started."
        }
    except Exception as e:
        print(e)
        #logger.error("Exception occurred starting workflow", exc_info=True)
        return {
            "message": "An error occurred starting the workflow"
        }
