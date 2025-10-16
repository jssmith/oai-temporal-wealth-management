import asyncio
import uuid
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
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
    function_tool,
    trace,
)

from common.account_context import ClientContext
from common.agent_constants import (
    BENE_AGENT_NAME,
    BENE_HANDOFF,
    BENE_INSTRUCTIONS,
    INVEST_AGENT_NAME,
    INVEST_HANDOFF,
    INVEST_INSTRUCTIONS,
    SUPERVISOR_AGENT_NAME,
    SUPERVISOR_HANDOFF,
    SUPERVISOR_INSTRUCTIONS,
)
from common.beneficiaries_manager import BeneficiariesManager
from common.investment_manager import InvestmentManager

# Import DB2Session for persistent conversation history
from common.db2_session import DB2Session
from common.db2_config import DB2Config

### Logging Configuration
# logging.basicConfig(level=logging.INFO,
#                     filename="basic.log",
#                     format="%(asctime)s | %(levelname)s | %(filename)s:%(lineno)s | %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.info("Wealth Management Chatbot Example Starting")

### Managers

investment_acct_mgr = InvestmentManager()
beneficiaries_mgr = BeneficiariesManager()

### Tools


@function_tool
async def add_beneficiaries(
    context: RunContextWrapper[ClientContext],
    client_id: str,
    first_name: str,
    last_name: str,
    relationship: str,
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
    # update the context
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
async def open_investment(
    context: RunContextWrapper[ClientContext], client_id: str, name: str, balance: str
):
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
    # update the context
    context.context.client_id = client_id
    return investment_acct_mgr.list_investment_accounts(client_id)


@function_tool
async def close_investment(
    context: RunContextWrapper[ClientContext], client_id: str, investment_id: str
):
    context.context.client_id = client_id
    # Note a real close investment would be much more complex and would not delete the actual account
    investment_acct_mgr.delete_investment_account(client_id, investment_id)


### Agents

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
    ],
)

beneficiary_agent.handoffs.append(supervisor_agent)
investment_agent.handoffs.append(supervisor_agent)


def format_history_item(item):
    """
    Extract readable text from conversation history items.
    Handles different message formats from the OpenAI agents framework.
    """
    # Handle simple user messages with role and content
    if isinstance(item, dict) and "role" in item and "content" in item:
        role = item["role"]
        content = item["content"]

        # Skip empty content
        if not content:
            return None

        # Handle string content
        if isinstance(content, str):
            if content.strip() == "":
                return None
            # Format user messages
            if role == "user":
                return f"User: {content}"
            elif role == "assistant":
                return f"Agent: {content}"

        # Handle list content (complex assistant message structures)
        elif isinstance(content, list) and len(content) > 0:
            # Extract text from complex structure like [{'text': '...', 'type': 'output_text'}]
            first_item = content[0]
            if isinstance(first_item, dict) and "text" in first_item:
                text = first_item["text"]
                if role == "assistant":
                    return f"Agent: {text}"
                elif role == "user":
                    return f"User: {text}"

    # Handle other message types that might have different structures
    if isinstance(item, dict):
        # Look for common patterns in agent messages
        if "agent" in item and "content" in item:
            agent_name = item.get("agent", {}).get("name", "Agent")
            content = item.get("content", "")
            if isinstance(content, list) and len(content) > 0:
                first_item = content[0]
                if isinstance(first_item, dict) and "text" in first_item:
                    return f"{agent_name}: {first_item['text']}"
            elif isinstance(content, str) and content.strip():
                return f"{agent_name}: {content}"

    # Skip items we can't parse or that are empty
    return None


async def main():
    current_agent: Agent[ClientContext] = supervisor_agent
    context = ClientContext()

    # Create or resume a conversation session
    try:
        conversation_id = input(
            "Enter conversation ID (or press Enter for new conversation): "
        ).strip()
        if not conversation_id:
            conversation_id = uuid.uuid4().hex[:16]
            print(f"Starting new conversation: {conversation_id}")
        else:
            print(f"Resuming conversation: {conversation_id}")
    except EOFError:
        # Handle non-interactive environment
        conversation_id = uuid.uuid4().hex[:16]
        print(f"Starting new conversation (non-interactive): {conversation_id}")

    # Initialize DB2Session for persistent conversation history
    # DB2 configuration - automatically loads from environment variables
    db2_config = DB2Config()

    session = DB2Session(session_id=conversation_id, config=db2_config)

    try:
        # Load existing conversation history
        existing_items = await session.get_items()
        if existing_items:
            print(
                f"Loaded {len(existing_items)} previous messages from conversation history."
            )
            # Display recent conversation history - show only user/agent messages
            history_messages = []
            for item in existing_items:
                formatted = format_history_item(item)
                if formatted:  # Only add successfully parsed messages
                    history_messages.append(formatted)

            # Show last 5 meaningful messages
            for message in history_messages[-5:]:
                print(f"[History] {message}")

        print("Welcome to ABC Wealth Management. How can I help you?")
        test_mode = False
        while True:
            try:
                user_input = input("Enter your message: ")
                lower_input = user_input.lower() if user_input is not None else ""
                if (
                    lower_input == "exit"
                    or lower_input == "end"
                    or lower_input == "quit"
                ):
                    break
            except EOFError:
                # Handle non-interactive environment - use a test message and exit after one iteration
                user_input = "Who are my beneficiaries?"
                print(f"Test message: {user_input}")
                lower_input = user_input.lower()
                test_mode = True

            with trace("wealth management", group_id=conversation_id):
                # Run the agent with the session-managed conversation history
                # The session automatically handles adding user messages and conversation history
                result = await Runner.run(
                    current_agent, user_input, session=session, context=context
                )

                for new_item in result.new_items:
                    agent_name = new_item.agent.name
                    if isinstance(new_item, MessageOutputItem):
                        print(
                            f"{agent_name} {ItemHelpers.text_message_output(new_item)}"
                        )
                    elif isinstance(new_item, HandoffOutputItem):
                        print(
                            f"Handed off from {new_item.source_agent.name} to {new_item.target_agent.name}"
                        )
                    elif isinstance(new_item, ToolCallItem):
                        print(f"{agent_name}: Calling a tool")
                    elif isinstance(new_item, ToolCallOutputItem):
                        print(f"{agent_name}: Tool call output: {new_item.output}")
                    else:
                        print(
                            f"{agent_name}: Skipping item: {new_item.__class__.__name__}"
                        )

                current_agent = result.last_agent

                # Exit after one iteration in test mode
                if test_mode:
                    break

    finally:
        # Clean up session
        session.close()
        print(
            f"Conversation {conversation_id} saved. You can resume it later by entering the same ID."
        )


if __name__ == "__main__":
    asyncio.run(main())
