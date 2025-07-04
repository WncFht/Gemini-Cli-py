import asyncio
import logging

from gemini_cli_core.core.app import GeminiClient
from gemini_cli_core.core.graphs.states import ConversationState
from gemini_cli_core.core.types import Content, NextSpeakerResponse

logger = logging.getLogger(__name__)

CHECK_PROMPT = """Analyze *only* the content and structure of your immediately preceding response (your last turn in the conversation history). Based *strictly* on that response, determine who should logically speak next: the 'user' or the 'model' (you).
**Decision Rules (apply in order):**
1.  **Model Continues:** If your last response explicitly states an immediate next action *you* intend to take (e.g., "Next, I will...", "Now I'll process...", "Moving on to analyze...", indicates an intended tool call that didn't execute), OR if the response seems clearly incomplete (cut off mid-thought without a natural conclusion), then the **'model'** should speak next.
2.  **Question to User:** If your last response ends with a direct question specifically addressed *to the user*, then the **'user'** should speak next.
3.  **Waiting for User:** If your last response completed a thought, statement, or task *and* does not meet the criteria for Rule 1 (Model Continues) or Rule 2 (Question to User), it implies a pause expecting user input or reaction. In this case, the **'user'** should speak next.
**Output Format:**
Respond *only* in JSON format according to the following schema. Do not include any text outside the JSON structure.
```json
{
  "type": "object",
  "properties": {
    "reasoning": {
        "type": "string",
        "description": "Brief explanation justifying the 'next_speaker' choice based *strictly* on the applicable rule and the content/structure of the preceding turn."
    },
    "next_speaker": {
      "type": "string",
      "enum": ["user", "model"],
      "description": "Who should speak next based *only* on the preceding turn and the decision rules."
    }
  },
  "required": ["next_speaker", "reasoning"]
}
```
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {
            "type": "string",
            "description": "Brief explanation justifying the 'next_speaker' choice based *strictly* on the applicable rule and the content/structure of the preceding turn.",
        },
        "next_speaker": {
            "type": "string",
            "enum": ["user", "model"],
            "description": "Who should speak next based *only* on the preceding turn and the decision rules",
        },
    },
    "required": ["reasoning", "next_speaker"],
}


def _is_function_response(content: Content) -> bool:
    """Checks if the content is a user message containing only function responses."""
    parts = content.get("parts", [])
    return (
        content.get("role") == "user"
        and bool(parts)
        and all("function_response" in part for part in parts)
    )


async def check_next_speaker(
    conversation_state: ConversationState,
    client: GeminiClient,
    signal: asyncio.Event | None = None,
) -> NextSpeakerResponse | None:
    """
    Checks and determines the next speaker in the conversation.
    This is a more complete Python port of `nextSpeakerChecker.ts`.
    """
    curated_history = conversation_state.get("curated_history", [])
    if not curated_history:
        return None

    comprehensive_history = conversation_state.get("comprehensive_history", [])
    if not comprehensive_history:
        return None

    last_comprehensive_message = comprehensive_history[-1]

    # Pre-check 1: If the last message is just tool responses, the model must go next.
    if _is_function_response(last_comprehensive_message):
        return NextSpeakerResponse(
            reasoning="Last message was a function response, so the model should speak next.",
            next_speaker="model",
        )

    # Pre-check 2: If the model's last turn was empty, it should continue.
    if last_comprehensive_message.get(
        "role"
    ) == "model" and not last_comprehensive_message.get("parts"):
        return NextSpeakerResponse(
            reasoning="Last message was an empty model turn, so the model should speak next.",
            next_speaker="model",
        )

    # If the last curated message isn't from the model, we can't decide.
    last_curated_message = curated_history[-1]
    if last_curated_message.get("role") != "model":
        return None

    # Fallback to LLM to decide.
    contents = [
        *curated_history,
        {"role": "user", "parts": [{"text": CHECK_PROMPT}]},
    ]

    try:
        result = await client.generate_json(
            contents=contents,
            schema=RESPONSE_SCHEMA,
            abort_signal=signal,
        )

        # Validate response
        if (
            result
            and "next_speaker" in result
            and result["next_speaker"] in ["user", "model"]
        ):
            return NextSpeakerResponse(
                reasoning=result.get("reasoning", ""),
                next_speaker=result["next_speaker"],
            )
        return None

    except Exception as e:
        logger.warning(
            "Failed to communicate with Gemini endpoint for next speaker check.",
            exc_info=e,
        )
        return None
