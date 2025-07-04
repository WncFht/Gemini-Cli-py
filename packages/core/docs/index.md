# Gemini CLI Core Documentation

Welcome to the documentation for `gemini-cli-core`, the powerful Python backend for the Gemini CLI.

`gemini-cli-core` is a sophisticated agentic backend powered by Python, FastAPI, and LangGraph. It's designed to provide the core intelligence for the Gemini CLI, enabling complex, multi-turn conversations, intelligent tool use, and stateful session management.

## Core Features

- **Agentic Logic with LangGraph**: At its heart, it uses a stateful graph to manage conversation flows, tool execution, and error handling.
- **Stateful Sessions**: Each user interaction is managed within a session, allowing for contextually aware, continuous conversations.
- **Extensible Tooling**: A flexible tool registry allows developers to easily add new capabilities for the agent to use, from file system operations to web searches.
- **Real-time Event Streaming**: Built with Server-Sent Events (SSE) to provide real-time feedback to the client, showing thought processes, tool calls, and final outputs.
- **Async-first Design**: Built on `asyncio` and `FastAPI` for high-performance, non-blocking I/O.

## Documentation Pages

Here is a guide to the different sections of this documentation:

- **[Getting Started](./getting-started.md)**: Your first stop. Learn how to set up your environment, install dependencies, and run the server.
- **[Architecture Overview](./architecture.md)**: Get a high-level view of the system's architecture, key components, and how they interact.
- **[Deep Dive: The Conversation Graph](./deep-dive-conversation-graph.md)**: A detailed look into the core of the agent's logic—the LangGraph state machine.
- **[Guide: Adding a New Tool](./guides-tool-development.md)**: A step-by-step guide on how to develop and integrate a new tool.
- **[API Reference](./api-reference.md)**: A reference for the FastAPI endpoints exposed by the server.

---
[中文文档](./zh/index.md)
