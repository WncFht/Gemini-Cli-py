# Gemini CLI Core - Python/LangGraph Implementation

这是 Gemini CLI 的 Python/LangGraph 重构版本，提供与原 TypeScript 版本完全兼容的 WebSocket API。

## 项目结构

```
core/
├── src/
│   ├── core/           # 核心模块
│   │   ├── config.py   # 配置管理
│   │   ├── events.py   # 事件系统
│   │   ├── types.py    # 类型定义
│   │   └── prompts.py  # 提示词模板
│   ├── graphs/         # LangGraph 图定义
│   │   └── states.py   # 状态定义
│   ├── websocket/      # WebSocket 服务器
│   │   └── server.py   # 服务器实现
│   └── __main__.py     # 主入口
├── pyproject.toml      # 项目配置
└── README.md          # 本文件
```

## 安装

1. 确保已安装 Python 3.12+
2. 安装 uv（如果尚未安装）：
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. 安装依赖：
   ```bash
   cd core
   uv sync
   ```

## 运行

### 开发模式

```bash
uv run python -m gemini_cli --debug
```

### 生产模式

```bash
uv run python -m gemini_cli --host 0.0.0.0 --port 8000
```

### 命令行参数

- `--host`: 绑定的主机地址（默认: 0.0.0.0）
- `--port`: 绑定的端口（默认: 8000）
- `--session-id`: 会话ID（默认: default）
- `--target-dir`: 操作目标目录（默认: 当前目录）
- `--model`: 使用的Gemini模型（默认: gemini-2.0-flash-exp）
- `--debug`: 启用调试模式

## API 兼容性

本实现保持与原 TypeScript 版本的完全兼容：

### WebSocket 端点

- `ws://localhost:8000/ws/{session_id}` - 主要的 WebSocket 连接端点
- `http://localhost:8000/health` - 健康检查端点

### 消息格式

#### 客户端 -> 服务器

1. 用户输入：
```json
{
  "type": "user_input",
  "value": "用户的消息内容"
}
```

2. 工具确认响应：
```json
{
  "type": "tool_confirmation_response",
  "callId": "tool_call_id",
  "outcome": "proceed|cancel|..."
}
```

3. 取消流：
```json
{
  "type": "cancel_stream"
}
```

#### 服务器 -> 客户端

所有事件使用驼峰命名以保持兼容：

```json
{
  "type": "model_response|tool_calls_update|error|...",
  "value": {
    // 事件具体数据
  }
}
```

## 开发状态

### 已完成（第一阶段）

- ✅ 项目结构设置
- ✅ 核心类型定义
- ✅ 配置管理系统
- ✅ 事件系统（保持驼峰命名兼容）
- ✅ WebSocket 服务器基础
- ✅ LangGraph 状态定义
- ✅ 提示词管理

### 待完成

- [ ] LangGraph 对话图实现
- [ ] 工具系统实现
- [ ] 模型接口集成
- [ ] 历史压缩功能
- [ ] 检查点功能
- [ ] 遥测系统
- [ ] 单元测试

## 测试

```bash
# 运行所有测试
uv run pytest

# 运行特定测试
uv run pytest tests/test_config.py

# 运行测试并生成覆盖率报告
uv run pytest --cov=gemini_cli
```

## 开发指南

### 使用 Makefile

项目提供了 Makefile 来简化常用命令：

```bash
# 安装依赖
make install

# 安装开发依赖
make dev

# 运行测试
make test

# 运行测试并生成覆盖率报告
make test-cov

# 格式化代码
make format

# 运行代码检查
make lint

# 运行类型检查
make type-check

# 运行所有检查（格式化、检查、类型检查）
make check

# 清理缓存文件
make clean

# 运行开发服务器
make run

# 运行生产服务器
make run-prod
```

### 代码风格

项目使用以下工具保证代码质量：

- **Ruff**: 代码格式化和检查（包含了所有 linting 和格式化功能）
- **mypy**: 静态类型检查

运行所有检查：
```bash
# 格式化代码
uv run ruff format .

# 运行代码检查并自动修复
uv run ruff check --fix .

# 仅检查不修复
uv run ruff check .

# 运行类型检查
uv run mypy .
```

### 添加新功能

1. 在相应模块中添加代码
2. 确保类型注解完整
3. 添加相应的测试
4. 更新文档

## 许可证

与原 Gemini CLI 项目保持一致。 