import argparse
import logging
import os

from .core import Config
from .websocket.server import GeminiWebSocketServer


def setup_logging(debug: bool = False) -> None:
    """设置日志配置"""
    level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Gemini CLI Core - Python/LangGraph implementation",
    )

    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind the server to (default: 0.0.0.0)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the server to (default: 8000)",
    )

    parser.add_argument(
        "--session-id",
        default="default",
        help="Session ID for the server (default: default)",
    )

    parser.add_argument(
        "--target-dir",
        default=os.getcwd(),
        help="Target directory for operations (default: current directory)",
    )

    parser.add_argument(
        "--model",
        default="gemini-2.0-flash-exp",
        help="Gemini model to use (default: gemini-2.0-flash-exp)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )

    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()

    # 设置日志
    setup_logging(args.debug)

    # 创建配置
    config = Config(
        session_id=args.session_id,
        model=args.model,
        target_dir=args.target_dir,
        debug_mode=args.debug,
    )

    # 创建并运行服务器
    server = GeminiWebSocketServer(config)

    logging.info(f"Starting Gemini CLI Core server on {args.host}:{args.port}")
    logging.info(f"Session ID: {args.session_id}")
    logging.info(f"Target directory: {args.target_dir}")
    logging.info(f"Model: {args.model}")

    # 运行服务器
    server.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
