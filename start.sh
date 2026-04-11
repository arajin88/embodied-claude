#!/bin/bash
# ダル君起動スクリプト
# exit後にこれを実行するだけでOK（--continue + Discord channels）
exec claude --continue --channels plugin:discord@claude-plugins-official
