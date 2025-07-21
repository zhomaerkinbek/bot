import os
import sqlite3, requests
from flask import Flask, request
from telegram import Bot, Update

# --- Настройки ---
TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_PATH = "/webhook"
PORT = int(os.environ.get("PORT", 8443))

# --- Flask и Bot ---
app = Flask(__name__)
bot = Bot(token=TOKEN)

# --- Синонимы и базовый ключ ---
# все мини-слова (lowercase) мапятся в один базовый:
SYNONYM_MAP = {
    "даниэль": "Даниэль",
    "даниэля": "Даниэль",
    "даниэлю": "Даниэль",
    "daniel":   "Даниэль",
    "даниэл":   "Даниэль",
}

# --- БД SQLite ---
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

def send_notification(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)

    if not (update.message and update.message.text):
        return "OK"

    text = update.message.text.lower()
    chat_id = update.effective_chat.id
    user = update.effective_user

    # --- Обработка команды /stats ---
    if text.startswith("/stats"):
        arg = "Даниэль".lower()
        base = SYNONYM_MAP.get(arg)
        if not base:
            base = arg.capitalize()  # если не в мапе, используем как есть
        cur.execute(
            "SELECT username, count FROM mentions WHERE word = ? ORDER BY count DESC",
            (base,),
        )
        rows = cur.fetchall()
        if not rows:
            send_notification(chat_id, f"Никто ещё не упоминал «{base}».")
        else:
            lines = [f"{u}: {c}" for u, c in rows]
            msg = f"📊 Статистика упоминаний «{base}»:\n" + "\n".join(lines)
            send_notification(chat_id, msg)
        return "OK"

    # --- Подсчёт упоминаний СИНОНИМОВ ---
    for form, base in SYNONYM_MAP.items():
        if form in text:
            # увеличиваем счётчик по базовому ключу
            cur.execute(
                """
                INSERT INTO mentions(word, user_id, username, count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(word, user_id) DO UPDATE SET count = count + 1;
                """,
                (base, user.id, user.full_name),
            )
            conn.commit()
            break

    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
