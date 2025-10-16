import asyncio
import logging
import os
from typing import Optional
from dotenv import load_dotenv

from agents import Model, ModelProvider, OpenAIChatCompletionsModel
import httpx
from openai import AsyncOpenAI
from temporalio.client import Client
from temporalio.worker import Worker

# Load environment variables from .env file
load_dotenv()

from common.client_helper import ClientHelper
from src.temporal.activities.clients import ClientActivities
from src.temporal.activities.open_account import OpenAccount
from temporalio.contrib.openai_agents import OpenAIAgentsPlugin

from src.temporal.claim_check.claim_check_plugin import ClaimCheckPlugin

from src.temporal.activities.beneficiaries import Beneficiaries
from src.temporal.activities.investments import Investments
from src.temporal.activities.db2_session_activities import DB2SessionActivities

from src.temporal.workflows.supervisor_workflow import WealthManagementWorkflow
from src.temporal.workflows.open_account_workflow import OpenInvestmentAccountWorkflow

# Read force_continue_as_new from environment variable
# Set to "true" or "1" to enable test mode for continue-as-new
FORCE_CONTINUE_AS_NEW = os.getenv("FORCE_CONTINUE_AS_NEW", "false").lower() in (
    "true",
    "1",
    "yes",
)


openai_client = AsyncOpenAI(
    base_url="https://api.openai.com/v1",  # Override for alternate endpoint
    api_key=os.getenv("OPENAI_API_KEY"),
    http_client=httpx.AsyncClient(
        verify=True,  # change to set client cert
    ),
)


class CustomModelProvider(ModelProvider):
    def get_model(self, model_name: Optional[str]) -> Model:
        model = OpenAIChatCompletionsModel(
            model=model_name if model_name else "gpt-4o",
            openai_client=openai_client,
        )
        return model


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(filename)s:%(lineno)s | %(message)s",
    )

    client_helper = ClientHelper()

    # Create client with plugins for workflow/activity execution
    plugins = [
        OpenAIAgentsPlugin(
            model_provider=CustomModelProvider(),
        ),
        ClaimCheckPlugin(),
    ]
    print(f"address is {client_helper.address} and plugins are {plugins}")
    client = await Client.connect(
        target_host=client_helper.address,
        namespace=client_helper.namespace,
        tls=client_helper.get_tls_config(),
        plugins=plugins,
    )

    # for the demo, we're using the same task queue as
    # the agents and the child workflow. In a production
    # situation, this would likely be a different task queue

    worker = Worker(
        client,
        task_queue=client_helper.taskQueue,
        workflows=[WealthManagementWorkflow, OpenInvestmentAccountWorkflow],
        activities=[
            Beneficiaries.list_beneficiaries,
            Beneficiaries.add_beneficiary,
            Beneficiaries.delete_beneficiary,
            Investments.list_investments,
            Investments.open_investment,
            Investments.close_investment,
            ClientActivities.get_client,
            ClientActivities.add_client,
            ClientActivities.update_client,
            OpenAccount.get_current_client_info,
            OpenAccount.update_client_details,
            OpenAccount.approve_kyc,
            DB2SessionActivities.get_items,
            DB2SessionActivities.add_items,
            DB2SessionActivities.pop_item,
            DB2SessionActivities.clear_session,
        ],
    )
    print(f"Running worker on {client_helper.address}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
