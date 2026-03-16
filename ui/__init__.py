# ui/__init__.py — Пакет главного окна Rozitta Parser
#
# Содержит:
#   ui/main_window.py — MainWindow, create_main_window(cfg, db)
#
# Правила пакета:
#   ✅ Можно импортировать PySide6 (это UI-слой)
#   ✅ Можно импортировать features/*/ui.py
#   ❌ Нельзя импортировать Telethon напрямую (только через features/*/api.py)
#   ❌ Нельзя открывать sqlite3 соединения (только через DBManager)
