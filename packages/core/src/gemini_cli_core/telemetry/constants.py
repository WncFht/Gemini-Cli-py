SERVICE_NAME = "gemini-cli"

# Event Names
EVENT_USER_PROMPT = "gemini_cli.user_prompt"
EVENT_TOOL_CALL = "gemini_cli.tool_call"
EVENT_API_REQUEST = "gemini_cli.api_request"
EVENT_API_ERROR = "gemini_cli.api_error"
EVENT_API_RESPONSE = "gemini_cli.api_response"
EVENT_CLI_CONFIG = "gemini_cli.config"

# Metric Names
METRIC_TOOL_CALL_COUNT = "gemini_cli.tool.call.count"
METRIC_TOOL_CALL_LATENCY = "gemini_cli.tool.call.latency"
METRIC_API_REQUEST_COUNT = "gemini_cli.api.request.count"
METRIC_API_REQUEST_LATENCY = "gemini_cli.api.request.latency"
METRIC_TOKEN_USAGE = "gemini_cli.token.usage"
METRIC_SESSION_COUNT = "gemini_cli.session.count"
METRIC_FILE_OPERATION_COUNT = "gemini_cli.file.operation.count"
