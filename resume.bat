@echo off
REM Dal-kun resume script (Windows)
REM Use this only to recover from a mid-session crash -- restores context with --continue.
REM For daily startup use start.bat instead.
claude --continue --channels plugin:discord@claude-plugins-official
