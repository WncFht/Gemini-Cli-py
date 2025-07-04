# Gemini CLI Core 文档

欢迎阅读 `gemini-cli-core` 的文档，这是 Gemini CLI 强大的 Python 后端。

`gemini-cli-core` 是一个由 Python、FastAPI 和 LangGraph 驱动的、先进的代理（Agent）后端。它旨在为 Gemini CLI 提供核心智能，以实现复杂的多轮对话、智能的工具使用和有状态的会话管理。

## 核心功能

- **基于 LangGraph 的代理逻辑**: 其核心使用一个有状态的图（Graph）来管理对话流、工具执行和错误处理。
- **有状态的会话**: 每一次用户交互都在一个会话中进行管理，从而实现具有上下文感知能力的连续对话。
- **可扩展的工具集**: 一个灵活的工具注册表允许开发者轻松地为代理添加新功能，从文件系统操作到网络搜索。
- **实时事件流**: 基于服务器发送事件（SSE）构建，为客户端提供实时反馈，展示思考过程、工具调用和最终输出。
- **异步优先设计**: 基于 `asyncio` 和 `FastAPI` 构建，以实现高性能、非阻塞的 I/O。

## 文档页面

以下是本文档不同部分的指南：

- **[快速上手](./getting-started.md)**: 您的第一站。学习如何设置环境、安装依赖以及运行服务器。
- **[架构概览](./architecture.md)**: 宏观了解系统的架构、关键组件以及它们之间的交互方式。
- **[深度解析：对话图](./deep-dive-conversation-graph.md)**: 详细了解代理逻辑的核心——LangGraph 状态机。
- **[开发指南：添加新工具](./guides-tool-development.md)**: 一步步指导您如何开发和集成一个新工具。
- **[API 参考](./api-reference.md)**: 服务器暴露的 FastAPI 端点的参考手册。

---
[English Version](../index.md) 