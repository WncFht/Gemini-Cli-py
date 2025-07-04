.PHONY: install dev test format lint type-check clean run

# 安装依赖
install:
	uv sync
	uv pip install -e . --no-deps

# 安装开发依赖
dev:
	uv sync --all-extras
	uv pip install -e . --no-deps

# 运行测试
test:
	uv run pytest

# 运行测试并生成覆盖率报告
test-cov:
	uv run pytest --cov=gemini_cli --cov-report=html

# 格式化代码
format:
	uv run ruff format .
	uv run ruff check --fix .

# 运行代码检查
lint:
	uv run ruff check .

# 运行类型检查
type-check:
	uv run mypy .

# 运行所有检查
check: format lint type-check

# 清理缓存文件
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +

# 运行开发服务器
run:
	uv run uvicorn gemini_cli_core.server:app --reload

# 运行生产服务器
run-prod:
	uv run uvicorn gemini_cli_core.server:app --host 0.0.0.0 --port 8000 