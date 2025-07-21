import os
import re
import sqlite3
import requests
from flask import Flask, request
from telegram import Bot, Update, MessageEntity
from telegram.error import TelegramError

# === Настройки ===
TOKEN        = os.environ["BOT_TOKEN"]
WEBHOOK_PATH = "/webhook"
PORT         = int(os.environ.get("PORT", 8443))

app = Flask(__name__)
bot = Bot(token=TOKEN)

# === База данных ===
conn = sqlite3.connect("debts.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      INTEGER NOT NULL,
    creditor_id  INTEGER NOT NULL,
    debtor_id    INTEGER NOT NULL,
    amount       REAL    NOT NULL,
    comment      TEXT,
    ts           DATETIME DEFAULT CURRENT_TIMESTAMP
);
""")
conn.commit()

# === Отправка сообщений ===
def send(chat_id: int, text: str):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

# === Извлечение целевого пользователя ===
def extract_target_user(update: Update):
    msg = update.message
    chat_id = msg.chat.id

    # 1) Пользователь – автор того сообщения, на которое ответили
    if msg.reply_to_message:
        return msg.reply_to_message.from_user

    # 2) По entity TEXT_MENTION (когда вы упоминаете контакт напрямую)
    if msg.entities:
        for ent in msg.entities:
            if ent.type == MessageEntity.TEXT_MENTION:
                return ent.user

            # 3) По обычному упоминанию @username
            if ent.type == MessageEntity.MENTION:
                username = msg.text[ent.offset : ent.offset + ent.length]  # e.g. "@ivan"
                try:
                    # Получаем информацию об участнике чата с этим username
                    member = bot.get_chat_member(chat_id, username)
                    return member.user
                except TelegramError:
                    return None

    return None

# === Вебхук ===
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
        target = extract_target_user(update)
        if not target:
            send(chat_id, "❗️Укажите пользователя через @username или ответом на его сообщение.")
            return "OK"

        m = re.match(r"^/addDebt\s+\S+\s+([\d.]+)(?:\s*-\s*(.+))?$", text)
        if not m:
            send(chat_id, "❗️Неверный формат.\nПример: /addDebt @user 100 - обед")
            return "OK"

        amt     = float(m.group(1))
        comment = m.group(2) or ""
        cur.execute(
            "INSERT INTO transactions(chat_id, creditor_id, debtor_id, amount, comment) VALUES(?,?,?,?,?)",
            (chat_id, me.id, target.id, amt, comment)
        )
        conn.commit()
        send(chat_id,
             f"✅ {target.full_name} теперь должен(на) вам {amt}₸"
             + (f" (\"{comment}\")" if comment else ""))
        return "OK"

    # --- /minusDebt ---
    if text.startswith("/minusDebt"):
        target = extract_target_user(update)
        if not target:
            send(chat_id, "❗️Укажите пользователя через @username или ответом на его сообщение.")
            return "OK"

        m = re.match(r"^/minusDebt\s+\S+\s+([\d.]+)$", text)
        if not m:
            send(chat_id, "❗️Неверный формат.\nПример: /minusDebt @user 50")
            return "OK"

        amt = float(m.group(1))
        # записываем отрицательную сумму в рамках этого чата
        cur.execute(
            "INSERT INTO transactions(chat_id, creditor_id, debtor_id, amount, comment) VALUES(?,?,?,?,?)",
            (chat_id, me.id, target.id, -amt, "возврат")
        )
        conn.commit()
        send(chat_id, f"✅ {target.full_name} вернул(а) вам {amt}₸")
        return "OK"

    # --- /stats ---
    if text.strip() == "/stats":
        cur.execute("""
            SELECT debtor_id, SUM(amount) as total
              FROM transactions
             WHERE creditor_id = ? AND chat_id = ?
             GROUP BY debtor_id
             HAVING total > 0
        """, (me.id, chat_id))
        rows = cur.fetchall()
        if not rows:
            send(chat_id, "📊 В этом чате никто вам не должен.")
        else:
            lines = []
            for debtor_id, total in rows:
                try:
                    usr = bot.get_chat(debtor_id)
                    name = " ".join(filter(None, [usr.first_name, usr.last_name]))
                except:
                    name = str(debtor_id)
                lines.append(f"{name}: {total}₸")
            msg = "📊 В этом чате вам должны:\n" + "\n".join(lines)
            send(chat_id, msg)
        return "OK"

    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
