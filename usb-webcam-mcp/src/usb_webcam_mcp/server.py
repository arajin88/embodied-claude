"""MCP Server for USB webcam capture."""

import base64
import io
import os
from datetime import datetime
from pathlib import Path
from typing import Any

# Suppress OpenCV error messages
os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["OPENCV_VIDEOIO_DEBUG"] = "0"

import cv2
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    ImageContent,
    TextContent,
    Tool,
)
from PIL import Image


server = Server("usb-webcam-mcp")

CAPTURE_DIR = Path(os.getenv("CAPTURE_DIR", os.path.join(os.path.expanduser("~"), ".cache", "usb-webcam-mcp")))
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

# Cache: camera_index -> (max_width, max_height)
_resolution_cache: dict[int, tuple[int, int]] = {}


def _detect_max_resolution(camera_index: int) -> tuple[int, int] | None:
    """Detect the maximum resolution for a camera and cache it."""
    if camera_index in _resolution_cache:
        return _resolution_cache[camera_index]

    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        return None
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 9999)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 9999)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        _resolution_cache[camera_index] = (w, h)
        return (w, h)
    finally:
        cap.release()


def find_available_cameras(max_cameras: int = 10) -> list[dict[str, Any]]:
    """Find available camera devices and cache their max resolutions."""
    cameras = []
    for i in range(max_cameras):
        res = _detect_max_resolution(i)
        if res is not None:
            cameras.append({
                "index": i,
                "max_width": res[0],
                "max_height": res[1],
            })
    return cameras


def capture_from_camera(
    camera_index: int = 0,
    width: int | None = None,
    height: int | None = None,
) -> bytes:
    """Capture an image from the specified camera at the best resolution."""
    if width is None or height is None:
        # Use cached max resolution
        res = _detect_max_resolution(camera_index)
        if res is not None:
            width, height = res
        else:
            raise RuntimeError(f"Cannot open camera at index {camera_index}")

    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera at index {camera_index}")

    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        for _ in range(10):
            cap.read()

        ret, frame = cap.read()
        if not ret or frame is None:
            raise RuntimeError(f"Failed to capture at {width}x{height} from camera {camera_index}")

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame_rgb)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()
    finally:
        cap.release()


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="list_cameras",
            description="List available camera devices connected to the system. These cameras serve as your eyes - your visual perception of the physical world.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="see",
            description="Capture an image from a USB webcam. This camera serves as your eyes - your visual perception of the physical world. Use this tool to see what's happening around you. Returns the image as base64-encoded JPEG.",
            inputSchema={
                "type": "object",
                "properties": {
                    "camera_index": {
                        "type": "integer",
                        "description": "Camera device index (default: 0)",
                        "default": 0,
                    },
                    "width": {
                        "type": "integer",
                        "description": "Desired image width in pixels (optional, defaults to max resolution)",
                    },
                    "height": {
                        "type": "integer",
                        "description": "Desired image height in pixels (optional, defaults to max resolution)",
                    },
                },
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent | ImageContent]:
    """Handle tool calls."""
    if name == "list_cameras":
        cameras = find_available_cameras()
        if not cameras:
            return [TextContent(type="text", text="No cameras found")]

        lines = ["Available cameras:"]
        for cam in cameras:
            lines.append(f"  - Index {cam['index']}: max {cam['max_width']}x{cam['max_height']}")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "see":
        camera_index = arguments.get("camera_index", 0)
        width = arguments.get("width")
        height = arguments.get("height")

        try:
            image_bytes = capture_from_camera(camera_index, width, height)
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")

            # Save image to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = CAPTURE_DIR / f"capture_{timestamp}_cam{camera_index}.jpg"
            file_path.write_bytes(image_bytes)

            return [
                ImageContent(
                    type="image",
                    data=image_base64,
                    mimeType="image/jpeg",
                ),
                TextContent(
                    type="text",
                    text=f"Saved: {file_path}",
                ),
            ]
        except RuntimeError as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run_server():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    """Entry point."""
    import asyncio
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
