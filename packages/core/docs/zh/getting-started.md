# 快速上手

本指南将引导您完成开发环境的设置、依赖项的安装，并首次运行 `gemini-cli-core` 服务器。

## 先决条件

- **Python**: 您需要 Python `3.12` 或更高版本。您可以使用 `python --version` 来检查您的版本。
- **`uv` (推荐)**: 本项目使用 `uv` 进行快速的依赖管理。您可以参考 [`uv` 官方安装指南](https://github.com/astral-sh/uv#installation)进行安装。虽然也可以使用 `pip`，但为了获得更好的性能，推荐使用 `uv`。

## 1. 克隆仓库

首先，如果您还没有克隆 Gemini CLI 的仓库，请将其克隆到您的本地计算机。

```bash
git clone https://github.com/your-org/gemini-cli.git
cd gemini-cli/packages/core
```

## 2. 设置虚拟环境

强烈建议在 Python 虚拟环境中工作。

**使用 `uv`:**
```bash
# 创建虚拟环境
uv venv

# 激活虚拟环境
# 在 macOS/Linux 上
source .venv/bin/activate
# 在 Windows 上
.venv\\Scripts\\activate
```

**使用 `venv` (标准库):**
```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# 在 macOS/Linux 上
source .venv/bin/activate
# 在 Windows 上
.venv\\Scripts\\activate
```

## 3. 安装依赖

激活虚拟环境后，安装所需的包。

**使用 `uv`:**
```bash
# 安装所有依赖，包括开发依赖
uv pip install -e .[dev]
```

**使用 `pip`:**
```bash
# 安装所有依赖，包括开发依赖
pip install -e .[dev]
```
`-e .` 会以"可编辑"模式安装项目，这对于开发非常有用。

## 4. 运行服务器

后端提供一个 FastAPI 服务器来处理 HTTP 请求。这是与代理进行聊天和会话管理的主要方式。

要运行服务器，请使用 `uvicorn`:

```bash
uvicorn gemini_cli_core.server:app --reload --host 0.0.0.0 --port 8000
```

- `--reload`: 启用热重载，当您修改代码时，服务器会自动重启。
- `--host 0.0.0.0`: 使服务器可以从您的本地计算机外部访问。
- `--port 8000`: 指定运行的端口。

您应该会看到类似以下的输出，表明服务器正在运行：
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx]
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

## 5. 访问 API 文档

服务器运行后，您可以在浏览器中访问交互式 API 文档（由 Swagger UI 提供）：

[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

您可以使用此界面直接测试 API 端点。现在，您已准备好开始开发了！ 