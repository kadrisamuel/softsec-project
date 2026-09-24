"""Application configuration options"""

import os
from pathlib import Path


class Config:  # pylint: disable=too-few-public-methods
    """Environment-sourced configuration options"""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SALT = os.environ.get("SALT", "tatou-auth")
    STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "./storage")).resolve()
    TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", "86400"))

    DB_USER = os.environ.get("DB_USER", "tatou")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "tatou")
    DB_HOST = os.environ.get("DB_HOST", "db")
    DB_PORT = int(os.environ.get("DB_PORT", "3306"))
    DB_NAME = os.environ.get("DB_NAME", "tatou")

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    ENABLE_MAIN_ROUTES = (os.environ.get("ENABLE_MAIN_ROUTES", "false").lower() == "true")
    ENABLE_AUTH_ROUTES = (os.environ.get("ENABLE_AUTH_ROUTES", "false").lower() == "true")
    ENABLE_DOCUMENT_ROUTES = (os.environ.get("ENABLE_DOCUMENT_ROUTES", "false").lower() == "true")
    ENABLE_WATERMARKING_ROUTES = (os.environ.get("ENABLE_WATERMARKING_ROUTES", "false").lower() == "true")
    ENABLE_RMAP_ROUTES = (os.environ.get("ENABLE_RMAP_ROUTES", "false").lower() == "true")
