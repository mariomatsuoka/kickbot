import asyncio
import json
import os
import re
import requests
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# --- CONFIGURAÇÕES ---
TELEGRAM_BOT_TOKEN = "8983993400:AAE4tPG0klN7X1cltSYbKQ3SphO1IKlytKY"
MY_TELEGRAM_ID = 5361059491
DATA_FILE = "streamers.json"
STATUS_FILE = "live_status.json"

# Estado da conversa
WAITING_STREAMER_NAME = 1

streamers = []
live_status = {}

# --- SERVIDOR WEB DUMMY PARA O RENDER ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot da Kick Privado ativo 24/7!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()

# --- FUNÇÕES DE DADOS ---
def load_data():
    global streamers, live_status
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                streamers = [s.strip().lower() for s in json.load(f)]
        except Exception:
            streamers = []
    else:
        streamers = []

    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r") as f:
                raw_status = json.load(f)
                live_status = {k.strip().lower(): v for k, v in raw_status.items()}
        except Exception:
            live_status = {}
    else:
        live_status = {}

def save_streamers():
    with open(DATA_FILE, "w") as f:
        json.dump(streamers, f)

def save_status():
    with open(STATUS_FILE, "w") as f:
        json.dump(live_status, f)

async def is_authorized(update: Update) -> bool:
    if update.effective_user.id != MY_TELEGRAM_ID:
        await update.message.reply_text("⛔ Acesso negado. Este bot é privado.")
        return False
    return True

def extract_streamer_name(input_text: str) -> str:
    input_text = input_text.strip().lower()
    match = re.search(r"kick\.com/([a-zA-Z0-9_]+)", input_text)
    if match:
        return match.group(1).lower()
    return input_text.replace("@", "").lower()

def check_channel_status(channel: str):
    url = f"https://kick.com/api/v1/channels/{channel}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get("livestream")
    except Exception as e:
        print(f"Erro ao consultar {channel}: {e}")
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update):
        return
    msg = (
        "👋 **Bot de Notificações da Kick Ativo na Nuvem!**\n\n"
        "• `/start` - Iniciar o bot\n"
        "• `/streamer` - Pedir e adicionar um streamer\n"
        "• `/delete <nome>` - Remover streamer da lista\n"
        "• `/list` - Listar streamers monitorados"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ask_streamer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update):
        return ConversationHandler.END

    await update.message.reply_text("✍️ **Por favor, digite apenas o nome do canal:**", parse_mode="Markdown")
    return WAITING_STREAMER_NAME

async def process_streamer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update):
        return ConversationHandler.END

    raw_input = update.message.text
    channel = extract_streamer_name(raw_input)

    if channel in streamers:
        await update.message.reply_text(f"⚠️ **{channel}** já está na sua lista.", parse_mode="Markdown")
        return ConversationHandler.END

    streamers.append(channel)
    save_streamers()

    loop = asyncio.get_event_loop()
    livestream = await loop.run_in_executor(None, lambda: check_channel_status(channel))

    if livestream is not None:
        live_status[channel] = True
        save_status()
        title = livestream.get("session_title", "Sem título")
        category = livestream.get("categories", [{}])[0].get("name", "Geral")
        stream_url = f"https://kick.com/{channel}"

        msg = (
            f"🔴 **{channel} está AO VIVO na Kick!**\n\n"
            f"📌 **Título:** {title}\n"
            f"🎮 **Categoria:** {category}\n\n"
            f"🎥 [Assistir à Transmissão]({stream_url})"
        )
    else:
        live_status[channel] = False
        save_status()
        msg = f"✅ **{channel}** adicionado à sua lista!\n\n⚪ **Status:** Offline no momento."

    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END

async def delete_streamer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update):
        return

    if not context.args:
        await update.message.reply_text("⚠️ Insira o nome do canal para remover.\nExemplo: `/delete gaules`", parse_mode="Markdown")
        return

    channel = extract_streamer_name(" ".join(context.args))

    found_channel = None
    for s in streamers:
        if s.lower() == channel:
            found_channel = s
            break

    if not found_channel:
        await update.message.reply_text(f"⚠️ **{channel}** não foi encontrado na sua lista.", parse_mode="Markdown")
        return

    streamers.remove(found_channel)
    if found_channel in live_status:
        del live_status[found_channel]
    
    save_streamers()
    save_status()

    await update.message.reply_text(f"🗑️ **{found_channel}** foi removido com sucesso e não será mais monitorado!", parse_mode="Markdown")

async def list_streamers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update):
        return

    if not streamers:
        await update.message.reply_text("📋 Sua lista está vazia. Use `/streamer` para adicionar.", parse_mode="Markdown")
        return

    lista = "\n".join([f"• {s}" for s in streamers])
    await update.message.reply_text(f"📋 **Seus streamers monitorados:**\n\n{lista}", parse_mode="Markdown")

async def check_kick_loop(app: Application):
    while True:
        current_streamers = list(streamers)
        for channel in current_streamers:
            if channel not in streamers:
                continue

            loop = asyncio.get_event_loop()
            livestream = await loop.run_in_executor(None, lambda: check_channel_status(channel))
            
            if channel not in streamers:
                continue

            was_live = live_status.get(channel, False)

            if livestream is not None and not was_live:
                live_status[channel] = True
                save_status()
                title = livestream.get("session_title", "Sem título")
                category = livestream.get("categories", [{}])[0].get("name", "Geral")
                stream_url = f"https://kick.com/{channel}"

                msg = (
                    f"🔴 **{channel} está AO VIVO na Kick!**\n\n"
                    f"📌 **Título:** {title}\n"
                    f"🎮 **Categoria:** {category}\n\n"
                    f"🎥 [Assistir à Transmissão]({stream_url})"
                )
                await app.bot.send_message(
                    chat_id=MY_TELEGRAM_ID,
                    text=msg,
                    parse_mode="Markdown"
                )

            elif livestream is None and was_live:
                live_status[channel] = False
                save_status()

        await asyncio.sleep(60)

async def post_init(app: Application):
    load_data()
    asyncio.create_task(check_kick_loop(app))

def main():
    Thread(target=run_web_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("streamer", ask_streamer_name),
        ],
        states={
            WAITING_STREAMER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_streamer_name)
            ],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("delete", delete_streamer))
    app.add_handler(CommandHandler("list", list_streamers))

    print("Bot rodando na nuvem...")
    app.run_polling()

if __name__ == "__main__":
    main()