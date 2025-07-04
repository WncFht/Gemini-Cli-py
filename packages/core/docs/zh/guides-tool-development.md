# 开发指南：添加新工具

通过添加自定义工具，可以为 `gemini-cli-core` 代理扩展新功能。您创建的任何新工具都将对语言模型可用，使其能够执行新的操作。

本指南涵盖了创建和注册新工具的过程。

## 1. `BaseTool` 抽象类

所有工具都必须继承自 `gemini_cli_core.tools.base.tool_base` 中的 `BaseTool` 抽象类。该类提供了系统与您的工具协作所需的基础结构。

以下是其关键组件的解析：

- **`__init__(self, ...)`**: 构造函数，您在此定义工具的元数据。
    - `name`: 工具的程序化名称（例如，`read_file`）。这是模型将使用的名称。
    - `display_name`: 一个人类可读的名称。
    - `description`: 详细说明该工具的功能、其参数的用途以及返回的内容。**这对模型理解如何以及何时使用您的工具至关重要。**
    - `parameter_schema`: 一个 Pydantic `BaseModel` 类，定义了您的工具接受的参数。

- **`async def execute(self, params: TParams, ...)`**: 您**必须**实现的抽象方法。
    - 这是您工具的核心逻辑所在。
    - 它接收参数（作为您的 Pydantic 模式的实例），并且必须返回一个 `ToolResult` 对象。

- **`ToolResult`**: 一个 Pydantic 模型，用于构造工具的输出。它有两个主要字段：
    - `llm_content`: 将发送回语言模型进行处理的详细输出。
    - `return_display`: 一个更简洁、人类可读的输出版本，可以直接显示给用户。

## 2. 示例：一个简单的 `echo` 工具

让我们创建一个简单的工具，它会回显一条消息。

### 步骤 2.1: 创建工具文件

创建一个新文件，例如 `gemini_cli_core/tools/custom/echo_tool.py`。

### 步骤 2.2: 定义参数模式

首先，为参数定义一个 Pydantic 模型。

```python
# gemini_cli_core/tools/custom/echo_tool.py
from pydantic import BaseModel, Field

class EchoParams(BaseModel):
    message: str = Field(description="要回显的消息。")
```

### 步骤 2.3: 实现工具类

现在，实现 `BaseTool` 的子类。

```python
# gemini_cli_core/tools/custom/echo_tool.py
from gemini_cli_core.tools.base import BaseTool, ToolResult
# ... (导入 EchoParams)

class EchoTool(BaseTool[EchoParams, ToolResult]):
    def __init__(self):
        super().__init__(
            name="echo",
            display_name="回显消息",
            description="一个接收消息并将其返回的简单工具。",
            parameter_schema=EchoParams.model_json_schema()
        )

    async def execute(self, params: EchoParams, **kwargs) -> ToolResult:
        output_message = f"模型说：{params.message}"
        
        return ToolResult(
            llm_content=output_message,
            return_display=output_message
        )
```

## 3. 注册工具

为了让系统找到您的工具，您需要注册它。虽然系统支持动态发现，但对于内置工具，最直接的方法是手动注册。

`ToolRegistry` 在 `Config` 对象 (`gemini_cli_core/core/config.py`) 中初始化。通常，您会在其创建后将您的工具添加到注册表中。

例如，您可以修改 `Config.get_tool_registry` 来包含您的新工具：

```python
# 在 gemini_cli_core/core/config.py 中（概念性示例）

# ...
from gemini_cli_core.tools.custom.echo_tool import EchoTool

class Config:
    # ...
    async def get_tool_registry(self) -> ToolRegistry:
        if self._tool_registry is None:
            self._tool_registry = ToolRegistry(self)
            
            # --- 在此处添加您的工具 ---
            self._tool_registry.register_tool(EchoTool())
            # --------------------------
            
            await self._tool_registry.discover_tools()
        return self._tool_registry
```

注册后，`echo` 工具将被包含在发送给 Gemini 模型的函数列表中，代理将能够在它认为合适的时候使用它。 