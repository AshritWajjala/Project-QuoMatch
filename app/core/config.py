from functools import lru_cache
from typing import Literal, Optional
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration for Project QuoMatch.
    Values can be overridden via environment variables or a .env file.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # --- Project Environment ---
    PROJECT_NAME: str = "Project-QuoMatch"
    ENVIRONMENT: Literal["development", "testing", "production"] = "development"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- LLM Client & Ollama Configurations ---
    OLLAMA_HOST_URL: Optional[str] = Field(
        default=None,
        description="Base URL for Ollama. Defaults to None (uses localhost:11434)."
    )
    OLLAMA_TIMEOUT: float = Field(
        default=300.0,
        description="Socket timeout in seconds for heavy vision pre-fill."
    )
    OLLAMA_TEMPERATURE: float = Field(
        default=0.0,
        description="Sampling temperature for deterministic structured extraction."
    )
    OLLAMA_NUM_CTX: int = Field(
        default=32768,
        description="Context window length (in tokens) to accommodate multi-page vision patches."
    )
    OLLAMA_NUM_PREDICT: int = Field(
        default=8192,
        description="Maximum generation tokens to prevent JSON truncation."
    )
    
    # --- Remote Execution & Network ---
    HOME_PC_IP: Optional[SecretStr] = Field(
        default=None,
        description="IP or Tailscale IP of the home workstation GPU node (stored as SecretStr).",
    )

    # --- Model Allocations ---
    # Dedicated models can be chosen per stage based on GPU constraints
    CLASSIFIER_MODEL: str = Field(
        default="qwen2.5vl:7b",
        description="Model used for Stage 1 page classification (Keep/Drop)."
    )
    EXTRACTOR_MODEL: str = Field(
        default="qwen2.5vl:7b",
        description="Model used for Stage 2 commercial table and item extraction."
    )
    MATCHING_MODEL: str = Field(
        default="qwen2.5vl:7b",
        description="Model used for text-only specification and BOM reconciliation."
    )

    # --- PDF & Image Processing Pipeline ---
    PDF_RENDER_DPI: int = Field(
        default=200,
        description="DPI used by PyMuPDF when rendering PDF pages into PIL Images."
    )
    IMAGE_CLASSIFICATION_MAX_DIM: int = Field(
        default=384,
        description="Thumbnail downscaling dimension for fast Stage 1 classification."
    )
    IMAGE_EXTRACTION_MAX_DIM: int = Field(
        default=1600,
        description="High-resolution max dimension to preserve fine table fonts in Stage 2."
    )
    IMAGE_JPEG_QUALITY: int = Field(
        default=85,
        description="JPEG compression quality when encoding PIL images to bytes."
    )

    # --- Deterministic Reconciliation & Commercial Rules ---
    RECONCILIATION_TOLERANCE: float = Field(
        default=0.05,
        description="Maximum acceptable absolute difference (delta) for currency rounding."
    )
    DEFAULT_MARGIN_PERCENT: float = Field(
        default=15.0,
        description="Default commercial resale markup percentage applied to vendor costs."
    )


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached singleton instance of the project settings.
    """
    return Settings()