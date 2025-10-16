from datetime import timedelta
import os

from temporalio import workflow
from temporalio.contrib import openai_agents
from temporalio.common import RetryPolicy

from common.user_message import (
    ProcessUserMessageInput,
    ProcessUserMessageResponse,
    ChatInteraction,
)
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
    OPEN_ACCOUNT_AGENT_NAME,
    OPEN_ACCOUNT_HANDOFF,
    OPEN_ACCOUNT_INSTRUCTIONS,
    ROUTING_GUARDRAIL_NAME,
    ROUTING_INSTRUCTIONS,
)

from src.temporal.activities.open_account import (
    OpenAccount,
    open_new_investment_account,
)
from common.account_context import UpdateAccountOpeningStateInput
from src.temporal.claim_check.claim_check_codec import ClaimCheckCodec
from src.temporal.services.workflow_request_service import WorkflowRequestService
from src.temporal.session.temporal_db2_session import TemporalDB2Session
from src.temporal.activities.db2_session_activities import DB2SessionActivities

with workflow.unsafe.imports_passed_through():
    from src.temporal.activities.beneficiaries import Beneficiaries
    from src.temporal.activities.investments import Investments
    from agents import (
        Agent,
        HandoffOutputItem,
        ItemHelpers,
        MessageOutputItem,
        RunConfig,
        Runner,
        ToolCallItem,
        ToolCallOutputItem,
        TResponseInputItem,
        input_guardrail,
        RunContextWrapper,
        GuardrailFunctionOutput,
        InputGuardrailTripwireTriggered,
    )
    from pydantic import BaseModel

### Configuration

# Read force_continue_as_new from environment variable at module load time
# Set to "true" or "1" to enable test mode for continue-as-new
FORCE_CONTINUE_AS_NEW = os.getenv("FORCE_CONTINUE_AS_NEW", "false").lower() in (
    "true",
    "1",
    "yes",
)

### Context


class WealthManagementContext(BaseModel):
    client_id: str | None = None


class RoutingGuardrailOutput(BaseModel):
    is_wealth_management_question: bool
    reasoning: str


routing_guardrail_agent = Agent(
    name=ROUTING_GUARDRAIL_NAME,
    instructions=ROUTING_INSTRUCTIONS,
    output_type=RoutingGuardrailOutput,
)


@input_guardrail
async def routing_guardrail(
    ctx: RunContextWrapper[WealthManagementContext],
    agent: Agent,
    input: str | list[TResponseInputItem],
) -> GuardrailFunctionOutput:
    workflow.logger.info(f"Guardrail triggered with input: {input}")

    if isinstance(input, list) and len(input) > 0:
        last_message = (
            input[-1].get("content", "")
            if isinstance(input[-1], dict)
            else str(input[-1])
        )
        workflow.logger.info(f"Analyzing message: {last_message}")
    else:
        last_message = str(input)
        workflow.logger.info(f"Analyzing message: {last_message}")

    result = await Runner.run(routing_guardrail_agent, input, context=ctx.context)

    workflow.logger.info(f"Guardrail result: {result.final_output}")
    should_block = not result.final_output.is_wealth_management_question
    workflow.logger.info(f"Should block: {should_block}")
    workflow.logger.info(
        f"Question is wealth management: {result.final_output.is_wealth_management_question}"
    )
    workflow.logger.info(f"Reasoning: {result.final_output.reasoning}")

    if should_block:
        workflow.logger.info(
            "Guardrail tripwire triggered! Blocking non-wealth-management question."
        )
    else:
        workflow.logger.info(
            "Guardrail allowing wealth management question to pass through."
        )

    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=should_block,
    )


### Agents
def init_agents(disable_guardrails: bool) -> Agent[WealthManagementContext]:
    """
    Initialize the agents for the Wealth Management Workflow

    Returns a supervisor agent
    """
    guardrails = []
    if not disable_guardrails:
        guardrails = [routing_guardrail]
    beneficiary_agent = Agent[WealthManagementContext](
        name=BENE_AGENT_NAME,
        handoff_description=BENE_HANDOFF,
        instructions=BENE_INSTRUCTIONS,
        tools=[
            openai_agents.workflow.activity_as_tool(
                Beneficiaries.list_beneficiaries,
                start_to_close_timeout=timedelta(seconds=5),
            ),
            openai_agents.workflow.activity_as_tool(
                Beneficiaries.add_beneficiary,
                start_to_close_timeout=timedelta(seconds=5),
            ),
            openai_agents.workflow.activity_as_tool(
                Beneficiaries.delete_beneficiary,
                start_to_close_timeout=timedelta(seconds=5),
            ),
        ],
        input_guardrails=guardrails,
    )

    open_account_agent = Agent[WealthManagementContext](
        name=OPEN_ACCOUNT_AGENT_NAME,
        handoff_description=OPEN_ACCOUNT_HANDOFF,
        instructions=OPEN_ACCOUNT_INSTRUCTIONS,
        tools=[
            open_new_investment_account,
            openai_agents.workflow.activity_as_tool(
                OpenAccount.get_current_client_info,
                start_to_close_timeout=timedelta(seconds=5),
            ),
            openai_agents.workflow.activity_as_tool(
                OpenAccount.approve_kyc, start_to_close_timeout=timedelta(seconds=5)
            ),
            openai_agents.workflow.activity_as_tool(
                OpenAccount.update_client_details,
                start_to_close_timeout=timedelta(seconds=5),
            ),
        ],
        input_guardrails=guardrails,
    )

    investment_agent = Agent[WealthManagementContext](
        name=INVEST_AGENT_NAME,
        handoff_description=INVEST_HANDOFF,
        instructions=INVEST_INSTRUCTIONS,
        tools=[
            openai_agents.workflow.activity_as_tool(
                Investments.list_investments,
                start_to_close_timeout=timedelta(seconds=5),
            ),
            openai_agents.workflow.activity_as_tool(
                Investments.close_investment,
                start_to_close_timeout=timedelta(seconds=5),
            ),
        ],
        handoffs=[open_account_agent],
        input_guardrails=guardrails,
    )

    supervisor_agent = Agent[WealthManagementContext](
        name=SUPERVISOR_AGENT_NAME,
        handoff_description=SUPERVISOR_HANDOFF,
        instructions=SUPERVISOR_INSTRUCTIONS,
        handoffs=[
            beneficiary_agent,
            investment_agent,
        ],
        input_guardrails=guardrails,
    )

    beneficiary_agent.handoffs.append(supervisor_agent)
    investment_agent.handoffs.append(supervisor_agent)
    open_account_agent.handoffs.append(investment_agent)
    return supervisor_agent


@workflow.defn
class WealthManagementWorkflow:
    def __init__(self):
        self.wf_id = workflow.info().workflow_id
        self.processed_response: list[ChatInteraction] | None = None
        self.run_config = RunConfig()
        self.agent_graph = {}
        self.current_agent = None
        self.context = WealthManagementContext()
        self.end_workflow = False
        self.sched_to_close_timeout = timedelta(seconds=5)
        self.retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            backoff_coefficient=2,
            maximum_interval=timedelta(seconds=30),
        )

        # Initialize request service for request/response coordination
        self.request_service = WorkflowRequestService()

        # Initialize Temporal-safe DB2 session for persistent conversation history
        # DB2 config is created in activities where environment variables can be safely read
        self.session = TemporalDB2Session(session_id=f"wf_{self.wf_id}")

        # Initialize claim check codec for cleanup (DISABLED FOR NOW)
        self.claim_check_codec: ClaimCheckCodec | None = None
        # self._initialize_claim_check_codec()  # Disabled - uncomment when needed

    def _init_agent_graph(self) -> dict[str, Agent[WealthManagementContext]]:
        """Initialize the agent graph and return a lookup dictionary."""
        supervisor = init_agents(True)

        # Build agent lookup dictionary
        agents = {SUPERVISOR_AGENT_NAME: supervisor}

        # Add all handoff agents
        for agent in supervisor.handoffs:
            agents[agent.name] = agent
            # Add nested handoffs
            for nested_agent in agent.handoffs:
                if nested_agent.name not in agents:
                    agents[nested_agent.name] = nested_agent

        workflow.logger.info(
            f"Initialized agent graph with agents: {list(agents.keys())}"
        )
        return agents

    def _get_agent_by_name(self, agent_name: str) -> Agent[WealthManagementContext]:
        """Get an agent by name from the agent graph."""
        if agent_name in self.agent_graph:
            return self.agent_graph[agent_name]
        workflow.logger.warning(
            f"Agent '{agent_name}' not found, defaulting to supervisor"
        )
        return self.agent_graph[SUPERVISOR_AGENT_NAME]

    def _initialize_claim_check_codec(self):
        """Initialize claim check codec for cleanup operations"""
        try:
            # DB2 config will be created in the codec where environment variables can be read
            # Note: This is currently disabled and may need refactoring to use activities
            self.claim_check_codec = ClaimCheckCodec()
            workflow.logger.info(
                f"Initialized claim check codec for workflow {self.wf_id}"
            )

        except Exception as e:
            workflow.logger.error(f"Failed to initialize claim check codec: {e}")
            self.claim_check_codec = None

    def _should_continue_as_new(self) -> bool:
        """Check if continue-as-new should be triggered."""
        # Use Temporal's suggestion based on workflow history size
        # Session data persists in DB2, so no need to check message count
        suggested = workflow.info().is_continue_as_new_suggested()
        if suggested:
            workflow.logger.info("Continue-as-new suggested by Temporal")
        return suggested

    async def _cleanup(self):
        """Clean up resources before workflow termination."""
        workflow.logger.info("Starting workflow cleanup")

        # Clean up claim check payloads for this workflow
        if self.claim_check_codec:
            try:
                await self.claim_check_codec.cleanup_workflow_payloads(
                    workflow_id=self.wf_id, workflow_run_id=workflow.info().run_id
                )
                workflow.logger.info(
                    f"Cleaned up claim check payloads for workflow {self.wf_id}"
                )
            except Exception as e:
                workflow.logger.error(f"Failed to cleanup claim check payloads: {e}")

            # Close claim check codec connections
            try:
                self.claim_check_codec.close()
                workflow.logger.info("Closed claim check codec")
            except Exception as e:
                workflow.logger.error(f"Failed to close claim check codec: {e}")

        # Note: DB2 session cleanup is not needed - activities handle connection lifecycle

    @workflow.run
    async def run(
        self,
        current_agent_name: str | None = None,
        context: WealthManagementContext | None = None,
    ):
        """
        Main workflow loop that processes user messages from the request service.
        Messages are queued by the update handler and processed serially here.

        Args:
            current_agent_name: Agent name to restore (for continue-as-new)
            context: Context to restore (for continue-as-new)

        Note:
            Continue-as-new mode is controlled by the FORCE_CONTINUE_AS_NEW environment variable.
        """
        # Initialize agent graph
        self.agent_graph = self._init_agent_graph()
        workflow.logger.info("Agent graph initialized")

        # Restore state from continue-as-new or initialize fresh
        if current_agent_name:
            self.current_agent = self._get_agent_by_name(current_agent_name)
            workflow.logger.info(f"Restored agent: {current_agent_name}")
        else:
            self.current_agent = self.agent_graph[SUPERVISOR_AGENT_NAME]

        if context:
            self.context = context
            workflow.logger.info(f"Restored context: {context}")
        else:
            self.context = WealthManagementContext()

        # Session automatically loads conversation history when used by Runner
        workflow.logger.info(f"Session initialized for workflow {self.wf_id}")

        while True:
            # Wait for next request or end signal
            workflow.logger.info("Waiting for next request or end signal")
            await workflow.wait_condition(
                lambda: self.request_service.has_requests() or self.end_workflow
            )

            # Check if we should end the workflow
            if self.end_workflow:
                workflow.logger.info("End workflow signal received, cleaning up")
                await self._cleanup()
                return

            # Get and process the next request
            req = await self.request_service.next_request()
            workflow.logger.info(f"Processing request: {req.message.user_input}")

            try:
                # Process the user message (session auto-saves to DB2)
                chat_interaction = await self._process_user_message_request(
                    req.message.user_input
                )

                # Update workflow details with recent conversation
                # await self._update_workflow_details()

                # Complete the request with success
                req.complete(
                    ProcessUserMessageResponse(
                        chat_interaction=chat_interaction, success=True
                    )
                )
                workflow.logger.info("Request completed successfully")

            except InputGuardrailTripwireTriggered as e:
                workflow.logger.info(f"Guardrail tripwire triggered: {e}")

                # Handle guardrail failure
                chat_interaction = ChatInteraction(
                    user_prompt=req.message.user_input, text_response=""
                )
                await self._handle_guardrail_failure(chat_interaction, e)

                # Update workflow details
                # await self._update_workflow_details()

                # Complete the request (still successful, just blocked)
                req.complete(
                    ProcessUserMessageResponse(
                        chat_interaction=chat_interaction, success=True
                    )
                )
                workflow.logger.info("Request completed with guardrail block")

            except Exception as e:
                workflow.logger.error(f"Error processing request: {e}")

                # Create error response
                error_chat = ChatInteraction(
                    user_prompt=req.message.user_input,
                    text_response="I'm sorry, there was an error processing your message. Please try again.",
                    json_response="",
                    agent_trace=f"Error: {str(e)}",
                )

                # Complete the request with error
                req.complete(
                    ProcessUserMessageResponse(
                        chat_interaction=error_chat, success=False, error_message=str(e)
                    )
                )
                workflow.logger.info("Request completed with error")

    async def _update_workflow_details(self) -> None:
        """Update workflow details with recent conversation history from session."""
        try:
            # Get last 10 items from session for display
            recent_items = await workflow.execute_activity(
                DB2SessionActivities.get_items,
                args=[
                    self.session.session_id,
                    None,  # config will be created in activity from env vars
                    10,  # limit
                    self.session.sessions_table,
                    self.session.messages_table,
                ],
                start_to_close_timeout=timedelta(seconds=10),
            )

            # Format for display
            if recent_items:
                details_parts = []
                for item in recent_items:
                    role = item.get("role", "")
                    content = item.get("content", "")
                    if role == "user":
                        details_parts.append(f"User: {content}")
                    elif role == "assistant":
                        details_parts.append(f"Agent: {content}")

                current_details = "\n\n".join(details_parts)
                workflow.set_current_details(current_details)

        except Exception as e:
            workflow.logger.warning(f"Failed to update workflow details: {e}")

    async def _process_user_message_request(self, message: str) -> ChatInteraction:
        """
        Process a user message and return the chat interaction.

        Args:
            message: The user's input message

        Returns:
            ChatInteraction with the agent's response
        """
        # Run the agent with session (session automatically manages conversation history)
        result = await Runner.run(
            self.current_agent,
            message,
            context=self.context,
            run_config=self.run_config,
            session=self.session,  # Session auto-loads history and auto-saves new messages
        )

        workflow.logger.info("Runner.run has exited.")

        # Update current agent from result
        self.current_agent = result.last_agent

        # Extract response components
        agent_trace, json_response, text_response = await self._process_llm_response(
            result
        )

        # Create and return chat interaction
        return ChatInteraction(
            user_prompt=message,
            text_response=text_response,
            json_response=json_response,
            agent_trace=agent_trace,
        )

    async def _handle_guardrail_failure(self, chat_interaction, e):
        workflow.logger.info(f"Guardrail tripwire triggered: {e}")
        text_response = "I'm sorry, but I can only help with wealth management questions related to beneficiaries and investments. Please ask me about your beneficiaries, investment accounts, or other wealth management topics."
        agent_trace = f"Guardrail blocked non-wealth-management question: {e}"
        if hasattr(e, "result") and hasattr(e.result, "output_info"):
            guardrail_output = e.result.output_info
            if hasattr(guardrail_output, "reasoning"):
                workflow.logger.info(
                    f"Blocked question reasoning: {guardrail_output.reasoning}"
                )
                agent_trace += f" - Reasoning: {guardrail_output.reasoning}"
        chat_interaction.text_response = text_response
        chat_interaction.json_response = ""
        chat_interaction.agent_trace = agent_trace

    async def _process_llm_response(self, result):
        text_response = ""
        json_response = ""
        agent_trace = ""
        for new_item in result.new_items:
            agent_name = new_item.agent.name
            if isinstance(new_item, MessageOutputItem):
                workflow.logger.info(
                    f"{agent_name} {ItemHelpers.text_message_output(new_item)}"
                )
                text_response += f"{ItemHelpers.text_message_output(new_item)}"
            elif isinstance(new_item, HandoffOutputItem):
                workflow.logger.info(
                    f"Handed off from {new_item.source_agent.name} to {new_item.target_agent.name}"
                )
                agent_trace += f"Handed off from {new_item.source_agent.name} to {new_item.target_agent.name}\n"
            elif isinstance(new_item, ToolCallItem):
                workflow.logger.info(f"{agent_name}: Calling a tool")
                agent_trace += f"{agent_name}: Calling a tool\n"
            elif isinstance(new_item, ToolCallOutputItem):
                workflow.logger.info(
                    f"{agent_name}: Tool call output: {new_item.output}"
                )
                json_response += new_item.output + "\n"
            else:
                agent_trace += (
                    f"{agent_name}: Skipping item: {new_item.__class__.__name__}\n"
                )
        return agent_trace, json_response, text_response

    @workflow.signal
    async def end_workflow(self):
        self.end_workflow = True

    @workflow.signal
    async def update_account_opening_state(
        self, state_input: UpdateAccountOpeningStateInput
    ):
        workflow.logger.info(
            f"Account Opening State changed {state_input.account_name} {state_input.state}"
        )
        # Status updates no longer sent to Redis - just log them

    @workflow.update
    async def process_user_message(
        self, message_input: ProcessUserMessageInput
    ) -> ProcessUserMessageResponse:
        """
        Queue a user message for processing and wait for the response.
        The actual processing happens in the workflow run loop.
        """
        workflow.logger.info(
            f"Update handler: Queueing user message: {message_input.user_input}"
        )

        # Delegate to request service - it handles queueing and waiting for response
        response = await self.request_service.do_request(message_input)

        workflow.logger.info("Update handler: Received response for message")
        return response
