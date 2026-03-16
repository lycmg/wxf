
import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量（本地运行时生效）
load_dotenv()

class Config:
    """Flask 应用配置类"""
    # Flask 基础配置
    SECRET_KEY = os.getenv("SECRET_KEY", "123")  # 会话密钥，默认值仅用于开发
    DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"  # 调试模式

    # API 密钥配置（从环境变量读取，绝不硬编码）
    BACKEND_API_KEY = os.getenv("BACKEND_API_KEY")  # Materials Project 密钥
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")  # DeepSeek 密钥

    # API 端点配置
    DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"

    # 应用业务配置
    DEFAULT_ELEMENT = "Ti"
    DEFAULT_MAX_RECORDS = 100
    RATE_LIMIT_DELAY = 0.5
    RESULTS_FOLDER = "results"