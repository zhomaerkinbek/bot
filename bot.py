import os
import sqlite3
from flask import Flask, request, abort
from telegram import Bot, Update

# 1) Параметры
TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_PATH = "/webhook"
PORT = int(os.environ.get("PORT", 8443))

# 2) Инициализация Flask и Telegram Bot
app = Flask(__name__)
bot = Bot(token=TOKEN)

# 3) Инициализация SQLite
conn = sqlite3.connect("mentions.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS mentions (
        word TEXT,
        user_id INTEGER,
        username TEXT,
        count INTEGER,
        PRIMARY KEY(word, user_id)
    );
""")
conn.commit()

TARGET_WORDS = ["Аня", "баг", "ошибка"]

# 4) Основной Webhook‑эндпоинт
@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if not data:
        return "no data", 400

    update = Update.de_json(data, bot)

    if update.message and update.message.text:
        text = update.message.text.lower()
        user = update.effective_user

        # подсчет упоминаний
        for word in TARGET_WORDS:
            if word.lower() in text:
                cur.execute(
                    """
                    INSERT INTO mentions(word, user_id, username, count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(word, user_id) DO UPDATE SET count = count + 1;
                    """,
                    (word, user.id, user.full_name),
                )
                conn.commit()
    return "OK"

# 5) Команда /stats (через отдельный маршрут)
@app.route("/stats/<word>", methods=["GET"])
def stats(word):
    cur.execute(
        "SELECT username, count FROM mentions WHERE word = ? ORDER BY count DESC",
        (word,),
    )
    rows = cur.fetchall()
    if not rows:
        return {"word": word, "stats": []}

    return {
        "word": word,
        "stats": [{ "user": u, "count": c } for u, c in rows]
    }

# 6) Запуск
if __name__ == "__main__":
    # Flask‑сервер на 0.0.0.0:$PORT
    app.run(host="0.0.0.0", port=PORT)
