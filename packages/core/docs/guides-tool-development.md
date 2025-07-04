# Guide: Adding a New Tool

The `gemini-cli-core` agent can be extended with new capabilities by adding custom tools. Any new tool you create will be available to the language model, allowing it to perform new actions.

This guide covers the process of creating and registering a new tool.

## 1. The `BaseTool` Abstract Class

All tools must inherit from the `BaseTool` abstract class, found in `gemini_cli_core.tools.base.tool_base`. This class provides the foundational structure that the system requires to work with your tool.

Here's a breakdown of its key components:

- **`__init__(self, ...)`**: The constructor where you define the tool's metadata.
    - `name`: The programmatic name for the tool (e.g., `read_file`). This is what the model will use.
    - `display_name`: A human-readable name.
    - `description`: A detailed explanation of what the tool does, what its parameters are for, and what it returns. **This is critical for the model to understand how and when to use your tool.**
    - `parameter_schema`: A Pydantic `BaseModel` class defining the arguments your tool accepts.

- **`async def execute(self, params: TParams, ...)`**: The abstract method you **must** implement.
    - This is where the core logic of your tool resides.
    - It receives the parameters (as an instance of your Pydantic schema) and must return a `ToolResult` object.

- **`ToolResult`**: A Pydantic model that structures the output of your tool. It has two main fields:
    - `llm_content`: The detailed output that will be sent back to the language model for processing.
    - `return_display`: A more concise, human-readable version of the output that can be shown directly to the user.

## 2. Example: A Simple `echo` Tool

Let's create a basic tool that echoes back a message.

### Step 2.1: Create the Tool File

Create a new file, for example, `gemini_cli_core/tools/custom/echo_tool.py`.

### Step 2.2: Define the Parameter Schema

First, define a Pydantic model for the parameters.

```python
# gemini_cli_core/tools/custom/echo_tool.py
from pydantic import BaseModel, Field

class EchoParams(BaseModel):
    message: str = Field(description="The message to echo back.")
```

### Step 2.3: Implement the Tool Class

Now, implement the `BaseTool` subclass.

```python
# gemini_cli_core/tools/custom/echo_tool.py
from gemini_cli_core.tools.base import BaseTool, ToolResult
# ... (import EchoParams)

class EchoTool(BaseTool[EchoParams, ToolResult]):
    def __init__(self):
        super().__init__(
            name="echo",
            display_name="Echo Message",
            description="A simple tool that takes a message and returns it.",
            parameter_schema=EchoParams.model_json_schema()
        )

    async def execute(self, params: EchoParams, **kwargs) -> ToolResult:
        output_message = f"The model said: {params.message}"
        
        return ToolResult(
            llm_content=output_message,
            return_display=output_message
        )
```

## 3. Registering the Tool

For the system to find your tool, you need to register it. While the system supports dynamic discovery, the most straightforward method for built-in tools is to register it manually.

The `ToolRegistry` is initialized within the `Config` object (`gemini_cli_core/core/config.py`). You would typically add your tool to the registry after it's created.

For example, you could modify `Config.get_tool_registry` to include your new tool:

```python
# In gemini_cli_core/core/config.py (conceptual example)

# ...
from gemini_cli_core.tools.custom.echo_tool import EchoTool

class Config:
    # ...
    async def get_tool_registry(self) -> ToolRegistry:
        if self._tool_registry is None:
            self._tool_registry = ToolRegistry(self)
            
            # --- Add your tool here ---
            self._tool_registry.register_tool(EchoTool())
            # --------------------------
            
            await self._tool_registry.discover_tools()
        return self._tool_registry
```

Once registered, the `echo` tool will be included in the list of functions sent to the Gemini model, and the agent will be able to use it whenever it deems appropriate.
