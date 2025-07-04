# Getting Started

This guide will walk you through setting up your development environment, installing dependencies, and running the `gemini-cli-core` server for the first time.

## Prerequisites

- **Python**: You need Python `3.12` or newer. You can check your version with `python --version`.
- **`uv` (Recommended)**: This project uses `uv` for fast dependency management. You can install it following the [official `uv` installation guide](https://github.com/astral-sh/uv#installation). While `pip` can also be used, `uv` is recommended for performance.

## 1. Clone the Repository

First, clone the Gemini CLI repository to your local machine if you haven't already.

```bash
git clone https://github.com/your-org/gemini-cli.git
cd gemini-cli/packages/core
```

## 2. Set Up a Virtual Environment

It's highly recommended to work within a Python virtual environment.

**With `uv`:**
```bash
# Create a virtual environment
uv venv

# Activate the virtual environment
# On macOS/Linux
source .venv/bin/activate
# On Windows
.venv\\Scripts\\activate
```

**With `venv` (standard library):**
```bash
# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# On macOS/Linux
source .venv/bin/activate
# On Windows
.venv\\Scripts\\activate
```

## 3. Install Dependencies

Once your virtual environment is activated, install the required packages.

**With `uv`:**
```bash
# Install all dependencies, including dev dependencies
uv pip install -e .[dev]
```

**With `pip`:**
```bash
# Install all dependencies, including dev dependencies
pip install -e .[dev]
```
The `-e .` installs the project in "editable" mode, which is useful for development.

## 4. Running the Server

The backend exposes a FastAPI server for handling HTTP requests. This is the primary way to interact with the agent for chat and session management.

To run the server, use `uvicorn`:

```bash
uvicorn gemini_cli_core.server:app --reload --host 0.0.0.0 --port 8000
```

- `--reload`: Enables hot-reloading, so the server will restart automatically when you make changes to the code.
- `--host 0.0.0.0`: Makes the server accessible from outside your local machine.
- `--port 8000`: Specifies the port to run on.

You should see output similar to this, indicating the server is running:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx]
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

## 5. Accessing the API Docs

Once the server is running, you can access the interactive API documentation (provided by Swagger UI) in your browser at:

[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

You can use this interface to test the API endpoints directly. You are now ready to start developing!
