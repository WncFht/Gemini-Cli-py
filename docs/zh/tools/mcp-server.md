# Gemini CLI 的 MCP 服务器

本文档提供了在 Gemini CLI 中配置和使用模型上下文协议 (MCP) 服务器的指南。

## 什么是 MCP 服务器？

MCP 服务器是一个应用程序，它通过模型上下文协议向 Gemini CLI 公开工具和资源，使其能够与外部系统和数据源进行交互。MCP 服务器充当 Gemini 模型与您的本地环境或其他服务（如 API）之间的桥梁。

MCP 服务器使 Gemini CLI 能够：

- **发现工具：** 通过标准化的模式定义列出可用的工具、其描述和参数。
- **执行工具：** 使用定义的参数调用特定的工具并接收结构化的响应。
- **访问资源：** 从特定资源读取数据（尽管 Gemini CLI 主要关注工具执行）。

通过 MCP 服务器，您可以扩展 Gemini CLI 的功能，以执行其内置功能之外的操作，例如与数据库、API、自定义脚本或专用工作流进行交互。

## 核心集成架构

Gemini CLI 通过内置于核心包 (`packages/core/src/tools/`) 中的复杂的发现和执行系统与 MCP 服务器集成：

### 发现层 (`mcp-client.ts`)

发现过程由 `discoverMcpTools()` 协调，它：

1. **遍历配置的服务器**，这些服务器来自您的 `settings.json` `mcpServers` 配置
2. 使用适当的传输机制（Stdio、SSE 或流式 HTTP）**建立连接**
3. 使用 MCP 协议从每个服务器**获取工具定义**
4. **清理和验证**工具模式以与 Gemini API 兼容
5. **在全局工具注册表中注册工具**并解决冲突

### 执行层 (`mcp-tool.ts`)

每个发现的 MCP 工具都包装在一个 `DiscoveredMCPTool` 实例中，该实例：

- 根据服务器信任设置和用户偏好**处理确认逻辑**
- 通过使用适当的参数调用 MCP 服务器来**管理工具执行**
- **处理响应**以供 LLM 上下文和用户显示
- **维护连接状态**并处理超时

### 传输机制

Gemini CLI 支持三种 MCP 传输类型：

- **Stdio 传输：** 生成一个子进程并通过 stdin/stdout 进行通信
- **SSE 传输：** 连接到服务器发送事件端点
- **流式 HTTP 传输：** 使用 HTTP 流进行通信

## 如何设置您的 MCP 服务器

Gemini CLI 使用您 `settings.json` 文件中的 `mcpServers` 配置来定位和连接到 MCP 服务器。此配置支持具有不同传输机制的多个服务器。

### 在 settings.json 中配置 MCP 服务器

您可以在 `~/.gemini/settings.json` 文件中在全局级别配置 MCP 服务器，或者在项目的根目录中创建或打开 `.gemini/settings.json` 文件。在该文件中，添加 `mcpServers` 配置块。

### 配置结构

将 `mcpServers` 对象添加到您的 `settings.json` 文件中：

```json
{ ...文件包含其他配置对象
  "mcpServers": {
    "serverName": {
      "command": "path/to/server",
      "args": ["--arg1", "value1"],
      "env": {
        "API_KEY": "$MY_API_TOKEN"
      },
      "cwd": "./server-directory",
      "timeout": 30000,
      "trust": false
    }
  }
}
```

### 配置属性

每个服务器配置都支持以下属性：

#### 必需（以下之一）

- **`command`** (字符串): Stdio 传输的可执行文件路径
- **`url`** (字符串): SSE 端点 URL (例如 `"http://localhost:8080/sse"`)
- **`httpUrl`** (字符串): HTTP 流端点 URL

#### 可选

- **`args`** (字符串[]): Stdio 传输的命令行参数
- **`env`** (对象): 服务器进程的环境变量。值可以使用 `$VAR_NAME` 或 `${VAR_NAME}` 语法引用环境变量
- **`cwd`** (字符串): Stdio 传输的工作目录
- **`timeout`** (数字): 请求超时（毫秒）（默认值：600,000 毫秒 = 10 分钟）
- **`trust`** (布尔值): 当为 `true` 时，绕过此服务器的所有工具调用确认（默认值：`false`）

### 示例配置

#### Python MCP 服务器 (Stdio)

```json
{
  "mcpServers": {
    "pythonTools": {
      "command": "python",
      "args": ["-m", "my_mcp_server", "--port", "8080"],
      "cwd": "./mcp-servers/python",
      "env": {
        "DATABASE_URL": "$DB_CONNECTION_STRING",
        "API_KEY": "${EXTERNAL_API_KEY}"
      },
      "timeout": 15000
    }
  }
}
```

#### Node.js MCP 服务器 (Stdio)

```json
{
  "mcpServers": {
    "nodeServer": {
      "command": "node",
      "args": ["dist/server.js", "--verbose"],
      "cwd": "./mcp-servers/node",
      "trust": true
    }
  }
}
```

#### 基于 Docker 的 MCP 服务器

```json
{
  "mcpServers": {
    "dockerizedServer": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "API_KEY",
        "-v",
        "${PWD}:/workspace",
        "my-mcp-server:latest"
      ],
      "env": {
        "API_KEY": "$EXTERNAL_SERVICE_TOKEN"
      }
    }
  }
}
```

#### 基于 HTTP 的 MCP 服务器

```json
{
  "mcpServers": {
    "httpServer": {
      "httpUrl": "http://localhost:3000/mcp",
      "timeout": 5000
    }
  }
}
```

## 发现过程深入探讨

当 Gemini CLI 启动时，它通过以下详细过程执行 MCP 服务器发现：

### 1. 服务器迭代和连接

对于 `mcpServers` 中配置的每个服务器：

1. **状态跟踪开始：** 服务器状态设置为 `CONNECTING`
2. **传输选择：** 基于配置属性：
   - `httpUrl` → `StreamableHTTPClientTransport`
   - `url` → `SSEClientTransport`
   - `command` → `StdioClientTransport`
3. **建立连接：** MCP 客户端尝试使用配置的超时进行连接
4. **错误处理：** 记录连接失败，并将服务器状态设置为 `DISCONNECTED`

### 2. 工具发现

连接成功后：

1. **工具列表：** 客户端调用 MCP 服务器的工具列表端点
2. **模式验证：** 验证每个工具的函数声明
3. **名称清理：** 清理工具名称以满足 Gemini API 要求：
   - 无效字符（非字母数字、下划线、点、连字符）替换为下划线
   - 超过 63 个字符的名称将被截断并进行中间替换 (`___`)

### 3. 冲突解决

当多个服务器公开同名工具时：

1. **首次注册获胜：** 第一个注册工具名称的服务器获得无前缀的名称
2. **自动加前缀：** 后续服务器获得带前缀的名称：`serverName__toolName`
3. **注册表跟踪：** 工具注册表维护服务器名称与其工具之间的映射

### 4. 模式处理

工具参数模式会经过清理以与 Gemini API 兼容：

- **`$schema` 属性**被移除
- **`additionalProperties`** 被剥离
- **带有 `default` 的 `anyOf`** 的默认值被移除（Vertex AI 兼容性）
- **递归处理**应用于嵌套模式

### 5. 连接管理

发现后：

- **持久连接：** 成功注册工具的服务器保持其连接
- **清理：** 未提供可用工具的服务器的连接被关闭
- **状态更新：** 最终服务器状态设置为 `CONNECTED` 或 `DISCONNECTED`

## 工具执行流程

当 Gemini 模型决定使用 MCP 工具时，会发生以下执行流程：

### 1. 工具调用

模型生成一个 `FunctionCall`，其中包含：

- **工具名称：** 已注册的名称（可能带前缀）
- **参数：** 与工具参数模式匹配的 JSON 对象

### 2. 确认过程

每个 `DiscoveredMCPTool` 都实现了复杂的确认逻辑：

#### 基于信任的绕过

```typescript
if (this.trust) {
  return false; // 无需确认
}
```

#### 动态允许列表

系统维护内部允许列表：

- **服务器级别：** `serverName` → 此服务器的所有工具都受信任
- **工具级别：** `serverName.toolName` → 此特定工具受信任

#### 用户选择处理

需要确认时，用户可以选择：

- **仅执行一次：** 仅这次执行
- **始终允许此工具：** 添加到工具级允许列表
- **始终允许此服务器：** 添加到服务器级允许列表
- **取消：** 中止执行

### 3. 执行

确认后（或信任绕过后）：

1. **参数准备：** 根据工具的模式验证参数
2. **MCP 调用：** 底层的 `CallableTool` 使用以下内容调用服务器：

   ```typescript
   const functionCalls = [
     {
       name: this.serverToolName, // 原始服务器工具名称
       args: params,
     },
   ];
   ```

3. **响应处理：** 格式化结果以供 LLM 上下文和用户显示

### 4. 响应处理

执行结果包含：

- **`llmContent`:** 用于语言模型上下文的原始响应部分
- **`returnDisplay`:** 用于用户显示的格式化输出（通常是 markdown 代码块中的 JSON）

## 如何与您的 MCP 服务器交互

### 使用 `/mcp` 命令

`/mcp` 命令提供有关您的 MCP 服务器设置的全面信息：

```bash
/mcp
```

这将显示：

- **服务器列表：** 所有配置的 MCP 服务器
- **连接状态：** `CONNECTED`、`CONNECTING` 或 `DISCONNECTED`
- **服务器详细信息：** 配置摘要（不包括敏感数据）
- **可用工具：** 每个服务器的工具列表及其描述
- **发现状态：** 整体发现过程状态

### `/mcp` 输出示例

```
MCP 服务器状态：

📡 pythonTools (CONNECTED)
  命令：python -m my_mcp_server --port 8080
  工作目录：./mcp-servers/python
  超时：15000 毫秒
  工具：calculate_sum、file_analyzer、data_processor

🔌 nodeServer (DISCONNECTED)
  命令：node dist/server.js --verbose
  错误：连接被拒绝

🐳 dockerizedServer (CONNECTED)
  命令：docker run -i --rm -e API_KEY my-mcp-server:latest
  工具：docker__deploy、docker__status

发现状态：COMPLETED
```

### 工具用法

发现后，MCP 工具就像内置工具一样可供 Gemini 模型使用。模型将自动：

1. 根据您的请求**选择适当的工具**
2. **显示确认对话框**（除非服务器受信任）
3. 使用适当的参数**执行工具**
4. 以用户友好的格式**显示结果**

## 状态监控和故障排除

### 连接状态

MCP 集成跟踪几种状态：

#### 服务器状态 (`MCPServerStatus`)

- **`DISCONNECTED`:** 服务器未连接或有错误
- **`CONNECTING`:** 正在尝试连接
- **`CONNECTED`:** 服务器已连接并准备就绪

#### 发现状态 (`MCPDiscoveryState`)

- **`NOT_STARTED`:** 发现尚未开始
- **`IN_PROGRESS`:** 正在发现服务器
- **`COMPLETED`:** 发现已完成（无论有无错误）

### 常见问题和解决方案

#### 服务器无法连接

**症状：** 服务器显示 `DISCONNECTED` 状态

**故障排除：**

1. **检查配置：** 验证 `command`、`args` 和 `cwd` 是否正确
2. **手动测试：** 直接运行服务器命令以确保其正常工作
3. **检查依赖项：** 确保已安装所有必需的包
4. **查看日志：** 在 CLI 输出中查找错误消息
5. **验证权限：** 确保 CLI 可以执行服务器命令

#### 未发现任何工具

**症状：** 服务器已连接但没有可用的工具

**故障排除：**

1. **验证工具注册：** 确保您的服务器实际注册了工具
2. **检查 MCP 协议：** 确认您的服务器正确实现了 MCP 工具列表
3. **查看服务器日志：** 检查 stderr 输出以查找服务器端错误
4. **测试工具列表：** 手动测试服务器的工具发现端点

#### 工具未执行

**症状：** 工具已发现但在执行期间失败

**故障排除：**

1. **参数验证：** 确保您的工具接受预期的参数
2. **模式兼容性：** 验证您的输入模式是否为有效的 JSON 模式
3. **错误处理：** 检查您的工具是否抛出未处理的异常
4. **超时问题：** 考虑增加 `timeout` 设置

#### 沙盒兼容性

**症状：** 启用沙盒时 MCP 服务器失败

**解决方案：**

1. **基于 Docker 的服务器：** 使用包含所有依赖项的 Docker 容器
2. **路径可访问性：** 确保服务器可执行文件在沙盒中可用
3. **网络访问：** 配置沙盒以允许必要的网络连接
4. **环境变量：** 验证是否传递了所需的环境变量

### 调试技巧

1. **启用调试模式：** 使用 `--debug_mode` 运行 CLI 以获取详细输出
2. **检查 stderr：** 捕获并记录 MCP 服务器 stderr（过滤 INFO 消息）
3. **隔离测试：** 在集成之前独立测试您的 MCP 服务器
4. **增量设置：** 在添加复杂功能之前从简单的工具开始
5. **频繁使用 `/mcp`：** 在开发过程中监控服务器状态

## 重要说明

### 安全注意事项

- **信任设置：** `trust` 选项绕过所有确认对话框。请谨慎使用，并且仅用于您完全控制的服务器
- **访问令牌：** 在配置包含 API 密钥或令牌的环境变量时要注意安全
- **沙盒兼容性：** 使用沙盒时，确保 MCP 服务器在沙盒环境中可用
- **私有数据：** 使用范围广泛的个人访问令牌可能会导致存储库之间的信息泄露

### 性能和资源管理

- **连接持久性：** CLI 与成功注册工具的服务器保持持久连接
- **自动清理：** 与未提供工具的服务器的连接会自动关闭
- **超时管理：** 根据服务器的响应特性配置适当的超时
- **资源监控：** MCP 服务器作为单独的进程运行并消耗系统资源

### 模式兼容性

- **属性剥离：** 系统会自动移除某些模式属性（`$schema`、`additionalProperties`）以与 Gemini API 兼容
- **名称清理：** 工具名称会自动清理以满足 API 要求
- **冲突解决：** 服务器之间的工具名称冲突通过自动加前缀解决

这种全面的集成使 MCP 服务器成为扩展 Gemini CLI 功能的强大方式，同时保持了安全性、可靠性和易用性。

</rewritten_file>