@echo off
REM Dal-kun debug startup script (Windows)
REM Fresh session + MCP debug logging enabled.
REM Debug log: C:\Users\araji\.claude\claude-mcp-debug.log
REM Use resume-debug.bat to resume with --continue + debug.
claude --channels plugin:discord@claude-plugins-official --debug mcp --debug-file C:/Users/araji/.claude/claude-mcp-debug.log
