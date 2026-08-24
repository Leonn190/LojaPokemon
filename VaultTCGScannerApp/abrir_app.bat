@echo off
cd /d "%~dp0"
py -3.12 main.py 2>nul || python main.py
