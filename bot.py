import os
import re
import requests
import pg8000.native as pg8000
from flask import Flask, request
from urllib.parse import urlparse
from telegram import Bot, Update, MessageEntity
from telegram.error import TelegramError

# === Настройки ===
TOKEN        = os.environ["BOT_TOKEN"]
WEBHOOK_PATH = "/webhook"
PORT         = int(os.environ.get("PORT", 8443))

app = Flask(__name__)
bot = Bot(token=TOKEN)

# === БД ===
url = urlparse(os.environ["DATABASE_URL"])
conn = pg8000.connect(
    user     = url.username,
    password = url.password,
    host     = url.hostname,
    port     = url.port or 5432,
    database = url.path.lstrip("/")
)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    creditor_id   INTEGER NOT NULL,
    debtor_id     INTEGER,           -- nullable, если используем plain-name
    debtor_name   TEXT,              -- nullable, только для plain-name
    amount        REAL    NOT NULL,
    comment       TEXT,
    ts            DATETIME DEFAULT CURRENT_TIMESTAMP
);
""")
conn.commit()

# === Утилита для отправки ===
def send(chat_id: int, text: str):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

# === Попытка распарсить упоминание пользователя ===
def extract_user(update: Update):
    msg = update.message
    # 1) reply
    if msg.reply_to_message:
        return msg.reply_to_message.from_user
    # 2) TEXT_MENTION
    if msg.entities:
        for ent in msg.entities:
            if ent.type == MessageEntity.TEXT_MENTION:
                return ent.user
    return None

# === Webhook ===
@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    if not (update.message and update.message.text):
        return "OK"

    text    = update.message.text.strip()
    chat_id = update.effective_chat.id
    me      = update.effective_user

    # --- /addDebt ---
    if text.startswith("/addDebt"):
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            send(chat_id, "❗️Формат: /addDebt <имя или @username> <сумма> [- комментарий]")
            return "OK"

        target_token = parts[1]
        rest = parts[2]

        # парсим сумму и комментарий
        m = re.match(r"^([\d.]+)(?:\s*-\s*(.+))?$", rest)
        if not m:
            send(chat_id, "❗️Неверный формат суммы. Пример: /addDebt John 100 - обед")
            return "OK"
        amt = float(m.group(1))
        comment = m.group(2) or ""

        # пытаемся извлечь реального User
        user_obj = extract_user(update)
        debtor_id = None
        debtor_name = None

        if target_token.startswith("@"):
            # plain @username: получаем через API getChat
            resp = requests.get(
                f"https://api.telegram.org/bot{TOKEN}/getChat",
                params={"chat_id": target_token}
            ).json()
            if resp.get("ok"):
                info = resp["result"]
                debtor_id = info["id"]
                debtor_name = None
            else:
                debtor_name = target_token.lstrip("@")
        elif user_obj and (user_obj.full_name.lower() in text.lower()):
            # reply-based mention
            debtor_id = user_obj.id
        else:
            # plain name
            debtor_name = target_token

        # INSERT
        cur.execute(
            """
            INSERT INTO transactions
                (chat_id, creditor_id, debtor_id, debtor_name, amount, comment)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chat_id, me.id, debtor_id, debtor_name, amt, comment)
        )
        conn.commit()

        who = debtor_name or f"{info.get('first_name','')} {info.get('last_name','')}".strip() or f"user {debtor_id}"
        send(chat_id,
             f"✅ Записано: {who} должен(на) вам {amt}С"
             + (f" («{comment}»)" if comment else ""))
        return "OK"

    # --- /minusDebt ---
    if text.startswith("/minusDebt"):
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            send(chat_id, "❗️Формат: /minusDebt <имя или @username> <сумма>")
            return "OK"

        target_token = parts[1]
        amt_str = parts[2]
        if not re.match(r"^[\d.]+$", amt_str):
            send(chat_id, "❗️Неверный формат суммы. Пример: /minusDebt John 50")
            return "OK"
        amt = float(amt_str)

        # разбираем аналогично addDebt
        user_obj = extract_user(update)
        debtor_id = None
        debtor_name = None

        if target_token.startswith("@"):
            resp = requests.get(
                f"https://api.telegram.org/bot{TOKEN}/getChat",
                params={"chat_id": target_token}
            ).json()
            if resp.get("ok"):
                debtor_id = resp["result"]["id"]
            else:
                debtor_name = target_token.lstrip("@")
        elif user_obj and (user_obj.full_name.lower() in text.lower()):
            debtor_id = user_obj.id
        else:
            debtor_name = target_token

        cur.execute(
            """
            INSERT INTO transactions
                (chat_id, creditor_id, debtor_id, debtor_name, amount, comment)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chat_id, me.id, debtor_id, debtor_name, -amt, "возврат")
        )
        conn.commit()

        who = debtor_name or resp["result"].get("first_name","") or f"user {debtor_id}"
        send(chat_id, f"✅ {who} вернул(а) вам {amt}С")
        return "OK"

    # --- /stats ---
    if text.strip() == "/stats":
        cur.execute("""
            SELECT
                COALESCE(debtor_name, '') as name_text,
                debtor_id,
                SUM(amount) as total
            FROM transactions
            WHERE creditor_id = ? AND chat_id = ?
            GROUP BY name_text, debtor_id
            HAVING total > 0
        """, (me.id, chat_id))
        rows = cur.fetchall()
        if not rows:
            send(chat_id, "📊 В этом чате никто вам не должен.")
        else:
            lines = []
            for name_text, did, total in rows:
                if did:
                    try:
                        u = bot.get_chat(did)
                        name = " ".join(filter(None,[u.first_name,u.last_name]))
                    except:
                        name = name_text or str(did)
                else:
                    name = name_text
                lines.append(f"{name}: {total}С")
            send(chat_id, "📊 Вам должны:\n" + "\n".join(lines))
        return "OK"

    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
