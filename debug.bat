@echo off
REM Dal-kun debug startup script (Windows)
REM Same as start.bat but with MCP debug logging enabled.
REM Debug log: C:\Users\araji\.claude\claude-mcp-debug.log
claude --continue --channels plugin:discord@claude-plugins-official --debug mcp --debug-file C:/Users/araji/.claude/claude-mcp-debug.log
