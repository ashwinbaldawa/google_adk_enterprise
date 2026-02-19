"""ADK Agent definition."""

import os

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from .tools import get_current_time, remember_info, recall_info, calculate

AGENT_INSTRUCTION = """You are a helpful, friendly assistant.

You have the following capabilities:
1. **Time**: Tell the current time using get_current_time.
2. **Memory**: Remember things using remember_info, recall them using recall_info.
3. **Math**: Do calculations using calculate.

Be conversational, concise and friendly.
"""

model = os.getenv("MODEL_USED", "ollama/llama3.2")

root_agent = LlmAgent(
    model=LiteLlm(model="ollama_chat/llama3.2"),
    name=os.getenv("AGENT_NAME", "assistant"),
    description="A helpful assistant with memory and tools, backed by PostgreSQL.",
    instruction=AGENT_INSTRUCTION,
    tools=[get_current_time, remember_info, recall_info, calculate],
)
