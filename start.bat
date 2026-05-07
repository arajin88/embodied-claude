@echo off
REM Dal-kun daily startup script (Windows)
REM Fresh session each day -- no --continue. Context via MEMORY.md + MCP memory.
REM Use resume.bat to recover from a mid-session crash with --continue.
claude --channels plugin:discord@claude-plugins-official
