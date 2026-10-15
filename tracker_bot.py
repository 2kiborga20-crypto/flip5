import asyncio
import aiohttp
import logging
import os
from telegram import Bot
from telegram.constants import ParseMode

# --- Конфигурация из переменных окружения Railway ---
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
    params = {
        "limit": 1000,
        "api_key": TONCENTER_API_KEY
    }
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
                logger.error(f"Ошибка API collections: {resp.status} - {await resp.text()}")
                return []
    except Exception as e:
        logger.error(f"Исключение при получении коллекций: {e}")
        return []

async def get_latest_transfers(session: aiohttp.ClientSession, collection_address: str):
    """Получает последние трансферы NFT для одной коллекции."""
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
        logger.error(f"Исключение при запросе трансферов для {collection_address}: {e}")
        return []

async def get_nft_image(session: aiohttp.ClientSession, nft_address: str):
    """Получает URL картинки NFT по его адресу."""
    url = "https://toncenter.com/api/v3/nft/items"
    params = {
        "address": nft_address,
        "api_key": TONCENTER_API_KEY
    }
    try:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                items = data.get("nft_items", [])
                if items:
                    previews = items[0].get("previews", [])
                    for p in previews:
                        if p.get("resolution") == "1500x1500":
                            return p.get("url")
                    metadata = items[0].get("metadata", {})
                    return metadata.get("image")
            return None
    except Exception as e:
        logger.error(f"Ошибка получения картинки: {e}")
        return None

async def process_transfer(transfer: dict, session: aiohttp.ClientSession):
    """Анализирует трансфер и отправляет уведомление."""
    global last_seen_lt
    lt = int(transfer.get("lt", 0))
    if lt <= last_seen_lt:
        return

    nft_address = transfer.get("nft_address", "неизвестно")
    new_owner = transfer.get("new_owner", "неизвестно")

    image_url = await get_nft_image(session, nft_address)

    caption = (
        f"🆕 <b>Обнаружено улучшение подарка до NFT!</b>\n\n"
        f"📍 <b>NFT:</b> <code>{nft_address}</code>\n"
        f"👤 <b>Новый владелец:</b> <code>{new_owner}</code>\n"
        f"🔗 <a href='https://tonviewer.com/{nft_address}'>Посмотреть в Tonviewer</a>"
    )

    try:
        if image_url:
            await bot.send_photo(
                chat_id=CHAT_ID,
                photo=image_url,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        else:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=caption,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        logger.info(f"Уведомление отправлено для NFT: {nft_address}")
        last_seen_lt = lt
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение: {e}")

async def main_loop():
    global last_seen_lt, gift_collections
    async with aiohttp.ClientSession() as session:
        gift_collections = await get_gift_collections(session)
        if not gift_collections:
            logger.error("Не удалось получить список коллекций. Проверьте API-ключ.")
            return

        initial_transfers = await get_latest_transfers(session, gift_collections[0])
        if initial_transfers:
            last_seen_lt = int(initial_transfers[0].get("lt", 0))
            logger.info(f"Начальный lt установлен: {last_seen_lt}")

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

            for transfer in all_transfers:
                await process_transfer(transfer, session)

            await asyncio.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main_loop())
