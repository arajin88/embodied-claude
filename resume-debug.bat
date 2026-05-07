@echo off
REM Dal-kun resume + debug script (Windows)
REM Use this to recover from a crash with --continue and MCP debug logging.
REM Debug log: C:\Users\araji\.claude\claude-mcp-debug.log
claude --continue --channels plugin:discord@claude-plugins-official --debug mcp --debug-file C:/Users/araji/.claude/claude-mcp-debug.log
