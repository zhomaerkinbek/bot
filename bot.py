import sys, platform
print(f"🛠️ Python: {platform.python_version()}, Telegram‑Bot: ", end="")
try:
    import telegram
    print(telegram.__version__)
except ImportError:
    print("telegram not installed")
import os
import logging
import sqlite3
from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

# --- Настройки ---
TOKEN = os.environ["BOT_TOKEN"]
TARGET_WORDS = ["Daniel", "Даниэль", "Даниэля", "Даниэлю", "Даниэлем"]

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

# --- Инициализация БД ---
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

# --- Обработчики ---
async def count_mentions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    user = update.effective_user
    lowered = text.lower()
    for word in TARGET_WORDS:
        if word.lower() in lowered:
            cur.execute(
                """
                INSERT INTO mentions(word, user_id, username, count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(word, user_id) DO UPDATE SET count = count + 1;
                """,
                (word, user.id, user.full_name),
            )
            conn.commit()

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Использование: /stats <слово>")
    word = context.args[0]
    cur.execute(
        "SELECT username, count FROM mentions WHERE word = ? ORDER BY count DESC",
        (word,),
    )
    rows = cur.fetchall()
    if not rows:
        return await update.message.reply_text(f"Никто не упоминал «{word}».")
    lines = [f"{u}: {c}" for u, c in rows]
    await update.message.reply_text("Статистика:\n" + "\n".join(lines))

# --- Запуск в webhook ---
if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, count_mentions))
    app.add_handler(CommandHandler("stats", stats_command))

    # Render автоматически задаёт эти переменные
    listen = "0.0.0.0"
    port = int(os.environ.get("PORT", "8443"))
    url_path = "webhook"
    # RENDER_EXTERNAL_URL — адрес вашего сервиса, например https://your-bot.onrender.com
    external = os.environ["RENDER_EXTERNAL_URL"]
    webhook_url = f"{external}/{url_path}"

    app.run_webhook(
        listen=listen,
        port=port,
        url_path=url_path,
        webhook_url=webhook_url
    )
