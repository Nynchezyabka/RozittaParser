import sqlite3
import os

db_path = r"D:\RozittaParser\RozittaParser\output\Чат. Мастер Группа Макеевой Виолетты\telegram_archive.db"

if not os.path.exists(db_path):
    print("Файл БД не найден:", db_path)
    exit(1)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# Кто пишет с user_id, но без username?
c.execute("SELECT DISTINCT user_id, username FROM messages WHERE username IS NULL OR username = '' LIMIT 20")
print("Без username (первые 20):", c.fetchall())

# Сколько уникальных авторов?
c.execute("SELECT COUNT(DISTINCT user_id) FROM messages")
print("Уникальных авторов:", c.fetchone()[0])

conn.close()