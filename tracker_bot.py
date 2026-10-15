import asyncio
import aiohttp
import logging
import os
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

# --- Конфигурация ---
TONCENTER_API_KEY = os.environ.get("TONCENTER_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 30))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
last_seen_lt = 0
gift_collections = []

async def get_gift_collections(session: aiohttp.ClientSession):
    """Автоматически получает список всех коллекций подарков."""
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
                logger.info(f"Найдено коллекций подарков: {len(gift_addrs)}")
                return gift_addrs
            else:
                logger.error(f"Ошибка API collections: {resp.status}")
                return []
    except Exception as e:
        logger.error(f"Исключение при получении коллекций: {e}")
        return []

async def get_latest_transfers(session: aiohttp.ClientSession, collection_address: str):
    url = "https://toncenter.com/api/v3/nft/transfers"
    params = {
        "collection_address": collection_address,
        "limit": 10,
        "sort": "desc",
        "api_key": TONCENTER_API_KEY
    }
    try:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("transfers", [])
            return []
    except Exception as e:
        logger.error(f"Ошибка трансферов {collection_address}: {e}")
        return []

async def get_nft_details(session: aiohttp.ClientSession, nft_address: str):
    """Получает картинку и адрес коллекции NFT."""
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
                    collection_addr = item.get("collection_address")
                    return image, collection_addr
            return None, None
    except Exception as e:
        logger.error(f"Ошибка деталей NFT: {e}")
        return None, None

def build_keyboard(nft_address: str, collection_addr: str, owner: str):
    """Собирает inline-кнопки под уведомлением."""
    buttons = [
        [
            InlineKeyboardButton(
                text="🖼 Открыть NFT",
                url=f"https://tonviewer.com/{nft_address}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="📦 Коллекция",
                url=f"https://tonviewer.com/{collection_addr}" if collection_addr else "https://tonviewer.com"
            ),
            InlineKeyboardButton(
                text="👤 Владелец",
                url=f"https://tonviewer.com/{owner}"
            ),
        ],
    ]
    return InlineKeyboardMarkup(buttons)

async def process_transfer(transfer: dict, session: aiohttp.ClientSession):
    global last_seen_lt
    lt = int(transfer.get("lt", 0))
    if lt <= last_seen_lt:
        return

    nft_address = transfer.get("nft_address", "")
    new_owner = transfer.get("new_owner", "")

    image_url, collection_addr = await get_nft_details(session, nft_address)

    caption = (
        f"🆕 <b>Обнаружено улучшение подарка до NFT!</b>\n\n"
        f"📍 <b>NFT:</b> <code>{nft_address}</code>\n"
        f"👤 <b>Владелец:</b> <code>{new_owner}</code>"
    )

    keyboard = build_keyboard(nft_address, collection_addr, new_owner)

    try:
        if image_url:
            await bot.send_photo(
                chat_id=CHAT_ID,
                photo=image_url,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        else:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        logger.info(f"Уведомление отправлено: {nft_address}")
        last_seen_lt = lt
    except Exception as e:
        logger.error(f"Не удалось отправить: {e}")

async def main_loop():
    global last_seen_lt, gift_collections
    async with aiohttp.ClientSession() as session:
        gift_collections = await get_gift_collections(session)
        if not gift_collections:
            logger.error("Не удалось получить коллекции. Проверь TONCENTER_API_KEY.")
            return

        initial = await get_latest_transfers(session, gift_collections[0])
        if initial:
            last_seen_lt = int(initial[0].get("lt", 0))
            logger.info(f"Начальный lt: {last_seen_lt}")

        cycle = 0
        while True:
            cycle += 1
            if cycle % 10 == 0:
                gift_collections = await get_gift_collections(session)

            all_transfers = []
            for addr in gift_collections:
                transfers = await get_latest_transfers(session, addr)
                all_transfers.extend(transfers)

            all_transfers.sort(key=lambda x: int(x.get("lt", 0)))
            for t in all_transfers:
                await process_transfer(t, session)

            await asyncio.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main_loop())
