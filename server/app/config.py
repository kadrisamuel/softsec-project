"""Application configuration options"""

import os
from pathlib import Path


class Config:  # pylint: disable=too-few-public-methods
    """Environment-sourced configuration options"""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SALT = os.environ.get("SALT", "tatou-auth")
    STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "./storage")).resolve()
    TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", "86400"))

    # ---------- DB config ----------
    DB_USER = os.environ.get("DB_USER", "tatou")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "tatou")
    DB_HOST = os.environ.get("DB_HOST", "db")
    DB_PORT = int(os.environ.get("DB_PORT", "3306"))
    DB_NAME = os.environ.get("DB_NAME", "tatou")

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- Route flags ----------
    ENABLE_MAIN_ROUTES = os.environ.get("ENABLE_MAIN_ROUTES", "false").lower() == "true"
    ENABLE_AUTH_ROUTES = os.environ.get("ENABLE_AUTH_ROUTES", "false").lower() == "true"
    ENABLE_DOCUMENT_ROUTES = (
        os.environ.get("ENABLE_DOCUMENT_ROUTES", "false").lower() == "true"
    )
    ENABLE_WATERMARKING_ROUTES = (
        os.environ.get("ENABLE_WATERMARKING_ROUTES", "false").lower() == "true"
    )
    ENABLE_RMAP_ROUTES = os.environ.get("ENABLE_RMAP_ROUTES", "false").lower() == "true"

    # ---------- RMAP config ----------
    RMAP_SERVER_PUBLIC_KEY_PATH = os.environ.get(
        "RMAP_SERVER_PUBLIC_KEY_PATH", "pub-keys/Group_02.asc"
    )
    RMAP_SERVER_PRIVATE_KEY_PATH = os.environ.get(
        "RMAP_SERVER_PRIVATE_KEY_PATH", "/run/secrets/private_key"
    )
    RMAP_SERVER_PRIVATE_KEY_PASS_FILE = os.environ.get(
        "RMAP_SERVER_PRIVATE_KEY_PASS_FILE", "/run/secrets/private_key_pass"
    )
    RMAP_CLIENT_KEYS_DIR = os.environ.get("RMAP_CLIENT_KEYS_DIR", "pub-keys")
    RMAP_WATERMARK_METHOD = os.environ.get("RMAP_WATERMARK_METHOD", "toy-eof")
    RMAP_LINK_PREFIX = os.environ.get(
        "RMAP_LINK_PREFIX",
        "http://softsec-group-02.dsv.local.su.se:5000/api/get-version/",
    )
    RMAP_WATERMARKING_KEY_PATH = os.environ.get("RMAP_WATERMARKING_KEY_PATH", "/run/secrets/watermarking_key")
