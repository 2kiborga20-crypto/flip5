import asyncio
import aiohttp
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Конфигурация ---
TONCENTER_API_KEY = os.environ.get("TONCENTER_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 30))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app_bot = None
last_seen_lt = 0
gift_collections = []
target_chat_id = CHAT_ID  # можно переопределить через /start

async def get_gift_collections(session: aiohttp.ClientSession):
    url = "https://toncenter.com/api/v3/nft/collections"
    params = {"limit": 1000, "api_key": TONCENTER_API_KEY}
    try:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                collections = data.get("collections", [])
                gift_addrs = []
                for c in collections:
                    raw = str(c).lower()
                    if "teleitem" in raw or "gift" in raw or "telegram" in raw:
                        addr = c.get("address")
                        if addr:
                            gift_addrs.append(addr)
                logger.info(f"Найдено коллекций: {len(gift_addrs)}")
                return gift_addrs
            else:
                logger.error(f"Ошибка collections: {resp.status}")
                return []
    except Exception as e:
        logger.error(f"Исключение collections: {e}")
        return []

async def get_latest_transfers(session, collection_address):
    url = "https://toncenter.com/api/v3/nft/transfers"
    params = {
        "collection_address": collection_address,
        "limit": 10, "sort": "desc",
        "api_key": TONCENTER_API_KEY
    }
    try:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("transfers", [])
            return []
    except Exception as e:
        logger.error(f"Ошибка трансферов: {e}")
        return []

async def get_nft_details(session, nft_address):
    url = "https://toncenter.com/api/v3/nft/items"
    params = {"address": nft_address, "api_key": TONCENTER_API_KEY}
    try:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                items = data.get("nft_items", [])
                if items:
                    item = items[0]
                    image = None
                    for p in item.get("previews", []):
                        if p.get("resolution") == "1500x1500":
                            image = p.get("url")
                            break
                    if not image:
                        image = item.get("metadata", {}).get("image")
                    return image, item.get("collection_address")
            return None, None
    except Exception as e:
        logger.error(f"Ошибка деталей: {e}")
        return None, None

def build_keyboard(nft_address, collection_addr, owner):
    buttons = [
        [InlineKeyboardButton("🖼 Открыть NFT", url=f"https://tonviewer.com/{nft_address}")],
        [
            InlineKeyboardButton("📦 Коллекция", url=f"https://tonviewer.com/{collection_addr}" if collection_addr else "https://tonviewer.com"),
            InlineKeyboardButton("👤 Владелец", url=f"https://tonviewer.com/{owner}"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)

async def process_transfer(transfer, session):
    global last_seen_lt
    lt = int(transfer.get("lt", 0))
    if lt <= last_seen_lt:
        return
    nft_address = transfer.get("nft_address", "")
    new_owner = transfer.get("new_owner", "")
    image_url, collection_addr = await get_nft_details(session, nft_address)
    caption = (
        f"🆕 <b>Обнаружено улучшение подарка!</b>\n\n"
        f"📍 <b>NFT:</b> <code>{nft_address}</code>\n"
        f"👤 <b>Владелец:</b> <code>{new_owner}</code>"
    )
    keyboard = build_keyboard(nft_address, collection_addr, new_owner)
    chat_to_send = target_chat_id
    if not chat_to_send:
        logger.warning("CHAT_ID не задан и /start не нажимали — некуда отправлять")
        last_seen_lt = lt
        return
    try:
        if image_url:
            await app_bot.send_photo(chat_id=chat_to_send, photo=image_url,
                                     caption=caption, parse_mode=ParseMode.HTML,
                                     reply_markup=keyboard)
        else:
            await app_bot.send_message(chat_id=chat_to_send, text=caption,
                                       parse_mode=ParseMode.HTML,
                                       reply_markup=keyboard,
                                       disable_web_page_preview=True)
        logger.info(f"Отправлено: {nft_address}")
        last_seen_lt = lt
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

async def main_loop():
    global last_seen_lt, gift_collections
    async with aiohttp.ClientSession() as session:
        gift_collections = await get_gift_collections(session)
        if not gift_collections:
            logger.error("Нет коллекций. Проверь TONCENTER_API_KEY.")
            return
        initial = await get_latest_transfers(session, gift_collections[0])
        if initial:
            last_seen_lt = int(initial[0].get("lt", 0))
            logger.info(f"Стартовый lt: {last_seen_lt}")
        cycle = 0
        while True:
            cycle += 1
            if cycle % 10 == 0:
                gift_collections = await get_gift_collections(session)
            all_transfers = []
            for addr in gift_collections:
                all_transfers.extend(await get_latest_transfers(session, addr))
            all_transfers.sort(key=lambda x: int(x.get("lt", 0)))
            for t in all_transfers:
                await process_transfer(t, session)
            await asyncio.sleep(POLL_INTERVAL)

# --- Telegram команды ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global target_chat_id
    target_chat_id = update.effective_chat.id
    logger.info(f"target_chat_id установлен: {target_chat_id}")
    await update.message.reply_text(
        f"👋 Привет! Я бот <b>flipnft</b>.\n\n"
        f"📡 Слежу за улучшениями подарков в TON.\n"
        f"🆔 Твой chat_id: <code>{target_chat_id}</code>\n\n"
        f"Теперь уведомления будут приходить сюда.",
        parse_mode=ParseMode.HTML
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 <b>Статус</b>\n\n"
        f"Коллекций: {len(gift_collections)}\n"
        f"Последний lt: {last_seen_lt}\n"
        f"Интервал: {POLL_INTERVAL} сек",
        parse_mode=ParseMode.HTML
    )

async def post_init(application: Application):
    global app_bot
    app_bot = application.bot
    asyncio.create_task(main_loop())

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    logger.info("Запуск бота...")
    app.run_polling()

if __name__ == "__main__":
    main()
