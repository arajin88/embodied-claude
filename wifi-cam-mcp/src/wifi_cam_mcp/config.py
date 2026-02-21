"""Configuration for WiFi Camera MCP Server."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Ensure .env is loaded from the project root (wifi-cam-mcp/), not CWD
_project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_project_root / ".env", override=True)


@dataclass(frozen=True)
class CameraConfig:
    """Camera connection configuration."""

    host: str
    username: str
    password: str
    onvif_port: int = 2020
    stream_url: str | None = None
    stream_username: str | None = None
    stream_password: str | None = None
    max_width: int = 3840
    max_height: int = 2160
    mount_mode: str = "normal"  # "normal" (desktop) or "ceiling" (inverted)

    @classmethod
    def from_env(cls, prefix: str = "TAPO") -> "CameraConfig":
        """Create config from environment variables.

        Args:
            prefix: Environment variable prefix (default: "TAPO")
                    For right camera, use "TAPO_RIGHT"
        """
        host = os.getenv(f"{prefix}_CAMERA_HOST", "") or os.getenv("TAPO_CAMERA_HOST", "")
        username = os.getenv(f"{prefix}_USERNAME", "") or os.getenv("TAPO_USERNAME", "")
        password = os.getenv(f"{prefix}_PASSWORD", "") or os.getenv("TAPO_PASSWORD", "")
        onvif_port = int(
            os.getenv(f"{prefix}_ONVIF_PORT", "") or os.getenv("TAPO_ONVIF_PORT", "") or "2020"
        )
        stream_url = os.getenv(f"{prefix}_STREAM_URL") or os.getenv("TAPO_STREAM_URL")
        stream_username = (
            os.getenv(f"{prefix}_STREAM_USERNAME") or os.getenv("TAPO_STREAM_USERNAME")
        )
        stream_password = (
            os.getenv(f"{prefix}_STREAM_PASSWORD") or os.getenv("TAPO_STREAM_PASSWORD")
        )
        mount_mode = (
            os.getenv(f"{prefix}_MOUNT_MODE", "") or os.getenv("TAPO_MOUNT_MODE", "") or "normal"
        ).lower()
        if mount_mode not in ("normal", "ceiling"):
            raise ValueError(f"Invalid mount mode '{mount_mode}'. Must be 'normal' or 'ceiling'.")
        max_width = int(os.getenv("CAPTURE_MAX_WIDTH", "3840"))
        max_height = int(os.getenv("CAPTURE_MAX_HEIGHT", "2160"))

        if not host:
            raise ValueError(f"{prefix}_CAMERA_HOST environment variable is required")
        if not username:
            raise ValueError(f"{prefix}_USERNAME environment variable is required")
        if not password:
            raise ValueError(f"{prefix}_PASSWORD environment variable is required")

        return cls(
            host=host,
            username=username,
            password=password,
            onvif_port=onvif_port,
            stream_url=stream_url,
            stream_username=stream_username,
            stream_password=stream_password,
            mount_mode=mount_mode,
            max_width=max_width,
            max_height=max_height,
        )

    @classmethod
    def right_camera_from_env(cls) -> "CameraConfig | None":
        """Create config for right camera if configured.

        Returns:
            CameraConfig for right camera, or None if not configured
        """
        host = os.getenv("TAPO_RIGHT_CAMERA_HOST", "")
        if not host:
            return None

        # Right camera can share username/password with left, or have its own
        username = os.getenv("TAPO_RIGHT_USERNAME", "") or os.getenv("TAPO_USERNAME", "")
        password = os.getenv("TAPO_RIGHT_PASSWORD", "") or os.getenv("TAPO_PASSWORD", "")
        onvif_port = int(
            os.getenv("TAPO_RIGHT_ONVIF_PORT", "") or os.getenv("TAPO_ONVIF_PORT", "") or "2020"
        )
        stream_url = os.getenv("TAPO_RIGHT_STREAM_URL")
        stream_username = (
            os.getenv("TAPO_RIGHT_STREAM_USERNAME") or os.getenv("TAPO_STREAM_USERNAME")
        )
        stream_password = (
            os.getenv("TAPO_RIGHT_STREAM_PASSWORD") or os.getenv("TAPO_STREAM_PASSWORD")
        )
        mount_mode = (
            os.getenv("TAPO_RIGHT_MOUNT_MODE", "") or os.getenv("TAPO_MOUNT_MODE", "") or "normal"
        ).lower()
        max_width = int(os.getenv("CAPTURE_MAX_WIDTH", "3840"))
        max_height = int(os.getenv("CAPTURE_MAX_HEIGHT", "2160"))

        if not username or not password:
            return None

        return cls(
            host=host,
            username=username,
            password=password,
            onvif_port=onvif_port,
            stream_url=stream_url,
            stream_username=stream_username,
            stream_password=stream_password,
            mount_mode=mount_mode,
            max_width=max_width,
            max_height=max_height,
        )


@dataclass(frozen=True)
class ServerConfig:
    """MCP Server configuration."""

    name: str = "wifi-cam-mcp"
    version: str = "0.1.0"
    capture_dir: str = ""

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Create config from environment variables."""
        default_dir = os.path.join(
            os.path.expanduser("~"), ".cache", "wifi-cam-mcp"
        )
        return cls(
            name=os.getenv("MCP_SERVER_NAME", "wifi-cam-mcp"),
            version=os.getenv("MCP_SERVER_VERSION", "0.1.0"),
            capture_dir=os.getenv("CAPTURE_DIR", default_dir),
        )
