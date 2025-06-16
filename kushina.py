import os
import logging
import random
import re
import asyncio
import threading
from urllib.parse import quote_plus, urlparse
from typing import Optional, Tuple, List
from io import BytesIO
from collections import deque
from dataclasses import dataclass

import aiohttp
from aiohttp import ClientTimeout, ClientResponseError

from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ChatAction, ChatType
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from telegram.error import BadRequest

# ====== Environment Setup ======
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN')
CHANNEL_LINK = os.getenv('CHANNEL_LINK', 'https://t.me/YourChannel')
GROUP_LINK = os.getenv('GROUP_LINK', 'https://t.me/YourSupportGroup')

# ====== Logging Configuration ======
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Dummy HTTP Server to Keep Render Happy ─────────────────────────────────
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def start_dummy_server():
    port = int(os.environ.get("PORT", 10000))  # Render injects this
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    print(f"Dummy server listening on port {port}")
    server.serve_forever()

# ====== Global Aiohttp Session ======
aiohttp_session: Optional[aiohttp.ClientSession] = None

# ====== Semaphores / Concurrency Limits ======
SEMAPHORE_FETCH = asyncio.Semaphore(50)
SEMAPHORE_DOWNLOAD = asyncio.Semaphore(20)

# ====== Waifu.pics SFW Categories ======
SFW_CATEGORIES = [
    'waifu', 'neko', 'shinobu', 'megumin', 'bully', 'cuddle', 'cry', 'hug',
    'awoo', 'kiss', 'lick', 'pat', 'smug', 'bonk', 'yeet', 'blush', 'smile',
    'wave', 'highfive', 'handhold', 'nom', 'bite', 'slap', 'kill', 'kick', 'happy',
    'wink', 'poke', 'dance', 'cringe'
]

# ====== NSFW Raw Tags for Rule34 (for /nsfw) ======
RAW_NSFW_TAGS = [
    "angelyeah", "aniflow", "xandit",
    "jellymation", "zaphn", "akajin", "suioresnu", "redhornyhead",
    "jakada", "laceysx", "lewdnatic", "s10collage", "kamuo",
    "kokoborohen", "totonito", "xtremetoons", "funhentaiparody",
    "imnotsassy", "mujitax", "gintsu", "shiina_ecchi", "maplestar",
    "overused23", "fountainpew", "maenchu", "henchan45",
    "sunahara_wataru", "mrchungus", "scy_25", "ribe-san",
    "optimystic", "d-art", "darkalx", "noxdsa", "dandanhub",
    "arthur4272", "visualtoon", "jack_.mery", "vizagege", "aqua051",
    "aindroidparanoid", "ahegao_ai", "artist request", "blk9201",
    "nyxworks", "airi_akura", "highheelfan", "5_nan_(5nan_5nan)",
    "nan5nan", "airiakane", "aianimearthd", "bubbleteexl", "banshou",
    "eroticgeek2", "dichareous", "shika-hina", "mandio_art",
    "noysca", "ceejss", "naruho", "deik0", "ni072", "agung911",
    "darkuro_27", "tenshin-ta", "callmesweet8", "narusakuart",
    "shib_ai", "neeba", "monyamonya78", "biggies00", "truevovan",
    "afrobull", "erogakure", "wakih", "iharuluna_(artist)",
    "raikage_art", "artkoikoi", "koikoi", "iroiro_tamadon",
    "maxx_saturn", "studio_oppai", "arte_eroge", "y_(artist)",
    "noddarts", "moonshades_(artist)", "fritzmeier", "abp_art",
    "dawho555", "artanis69", "juanpiamvs", "lyumus", "kumostudios",
    "queentsunade", "paledisc", "reinsmash", "jesko_(pixiv)",
    "indrockz", "n/a_(artist)", "echigakureart", "veruvia12",
    "rantuahelax", "raiha", "eregsi", "afw", "afw_edit",
    "wpixxx(artist)", "scarecrowpink", "lenacringe", "leinadxxx",
    "ikisugimaru1919", "awesomegio", "aldwelter", "thefarquad",
    "tbaanime", "zuharu", "mrhnsfw", "jyacira1", "arekusanderu",
    "yomi_ink", "leozurcxxx"
]

# ====== GIF_TAGS for /gif command only ======
GIF_TAGS = [
    "angelyeah", "aniflow", "xandit",
    "jellymation", "zaphn", "akajin", "suioresnu", "redhornyhead",
    "jakada", "laceysx", "lewdnatic", "s10collage", "kamuo",
    "kokoborohen", "totonito", "xtremetoons", "funhentaiparody",
    "imnotsassy", "mujitax", "gintsu", "shiina_ecchi", "maplestar",
    "overused23", "fountainpew", "maenchu", "henchan45",
    "sunahara_wataru", "mrchungus", "scy_25", "ribe-san",
    "optimystic", "d-art", "darkalx", "noxdsa", "dandanhub",
    "arthur4272", "visualtoon", "jack_.mery", "vizagege", "aqua051",
    "aindroidparanoid", "ahegao_ai", "artist request", "blk9201",
    "nyxworks", "airi_akura", "highheelfan", "5_nan_(5nan_5nan)",
    "nan5nan", "airiakane", "aianimearthd", "bubbleteexl", "banshou",
    "eroticgeek2", "dichareous", "shika-hina", "mandio_art",
    "noysca", "ceejss", "naruho", "deik0", "ni072", "agung911",
    "darkuro_27", "tenshin-ta", "callmesweet8", "narusakuart",
    "shib_ai", "neeba", "monyamonya78", "biggies00", "truevovan",
    "afrobull", "erogakure", "wakih", "iharuluna_(artist)",
    "raikage_art", "artkoikoi", "koikoi", "iroiro_tamadon",
    "maxx_saturn", "studio_oppai", "arte_eroge", "y_(artist)",
    "noddarts", "moonshades_(artist)", "fritzmeier", "abp_art",
    "dawho555", "artanis69", "juanpiamvs", "lyumus", "kumostudios",
    "queentsunade", "paledisc", "reinsmash", "jesko_(pixiv)",
    "indrockz", "n/a_(artist)", "echigakureart", "veruvia12",
    "rantuahelax", "raiha", "eregsi", "afw", "afw_edit",
    "wpixxx(artist)", "scarecrowpink", "lenacringe", "leinadxxx",
    "ikisugimaru1919", "awesomegio", "aldwelter", "thefarquad",
    "tbaanime", "zuharu", "mrhnsfw", "jyacira1", "arekusanderu",
    "yomi_ink", "leozurcxxx"
]

# ====== PHOTO_TAGS for /photo command only ======
PHOTO_TAGS = [
    "angelyeah", "aniflow", "xandit",
    "jellymation", "zaphn", "akajin", "suioresnu", "redhornyhead",
    "jakada", "laceysx", "lewdnatic", "s10collage", "kamuo",
    "kokoborohen", "totonito", "xtremetoons", "funhentaiparody",
    "imnotsassy", "mujitax", "gintsu", "shiina_ecchi", "maplestar",
    "overused23", "fountainpew", "maenchu", "henchan45",
    "sunahara_wataru", "mrchungus", "scy_25", "ribe-san",
    "optimystic", "d-art", "darkalx", "noxdsa", "dandanhub",
    "arthur4272", "visualtoon", "jack_.mery", "vizagege", "aqua051",
    "aindroidparanoid", "ahegao_ai", "artist request", "blk9201",
    "nyxworks", "airi_akura", "highheelfan", "5_nan_(5nan_5nan)",
    "nan5nan", "airiakane", "aianimearthd", "bubbleteexl", "banshou",
    "eroticgeek2", "dichareous", "shika-hina", "mandio_art",
    "noysca", "ceejss", "naruho", "deik0", "ni072", "agung911",
    "darkuro_27", "tenshin-ta", "callmesweet8", "narusakuart",
    "shib_ai", "neeba", "monyamonya78", "biggies00", "truevovan",
    "afrobull", "erogakure", "wakih", "iharuluna_(artist)",
    "raikage_art", "artkoikoi", "koikoi", "iroiro_tamadon",
    "maxx_saturn", "studio_oppai", "arte_eroge", "y_(artist)",
    "noddarts", "moonshades_(artist)", "fritzmeier", "abp_art",
    "dawho555", "artanis69", "juanpiamvs", "lyumus", "kumostudios",
    "queentsunade", "paledisc", "reinsmash", "jesko_(pixiv)",
    "indrockz", "n/a_(artist)", "echigakureart", "veruvia12",
    "rantuahelax", "raiha", "eregsi", "afw", "afw_edit",
    "wpixxx(artist)", "scarecrowpink", "lenacringe", "leinadxxx",
    "ikisugimaru1919", "awesomegio", "aldwelter", "thefarquad",
    "tbaanime", "zuharu", "mrhnsfw", "jyacira1", "arekusanderu",
    "yomi_ink", "leozurcxxx"
]

# ====== VIDEO_TAGS for /video command only ======
VIDEO_TAGS = [
    "angelyeah", "aniflow", "xandit",
    "jellymation", "zaphn", "akajin", "suioresnu", "redhornyhead",
    "jakada", "laceysx", "lewdnatic", "s10collage", "kamuo",
    "kokoborohen", "totonito", "xtremetoons", "funhentaiparody",
    "imnotsassy", "mujitax", "gintsu", "shiina_ecchi", "maplestar",
    "overused23", "fountainpew", "maenchu", "henchan45",
    "sunahara_wataru", "mrchungus", "scy_25", "ribe-san",
    "optimystic", "d-art", "darkalx", "noxdsa", "dandanhub",
    "arthur4272", "visualtoon", "jack_.mery", "vizagege", "aqua051",
    "aindroidparanoid", "ahegao_ai", "artist request", "blk9201",
    "nyxworks", "airi_akura", "highheelfan", "5_nan_(5nan_5nan)",
    "nan5nan", "airiakane", "aianimearthd", "bubbleteexl", "banshou",
    "eroticgeek2", "dichareous", "shika-hina", "mandio_art",
    "noysca", "ceejss", "naruho", "deik0", "ni072", "agung911",
    "darkuro_27", "tenshin-ta", "callmesweet8", "narusakuart",
    "shib_ai", "neeba", "monyamonya78", "biggies00", "truevovan",
    "afrobull", "erogakure", "wakih", "iharuluna_(artist)",
    "raikage_art", "artkoikoi", "koikoi", "iroiro_tamadon",
    "maxx_saturn", "studio_oppai", "arte_eroge", "y_(artist)",
    "noddarts", "moonshades_(artist)", "fritzmeier", "abp_art",
    "dawho555", "artanis69", "juanpiamvs", "lyumus", "kumostudios",
    "queentsunade", "paledisc", "reinsmash", "jesko_(pixiv)",
    "indrockz", "n/a_(artist)", "echigakureart", "veruvia12",
    "rantuahelax", "raiha", "eregsi", "afw", "afw_edit",
    "wpixxx(artist)", "scarecrowpink", "lenacringe", "leinadxxx",
    "ikisugimaru1919", "awesomegio", "aldwelter", "thefarquad",
    "tbaanime", "zuharu", "mrhnsfw", "jyacira1", "arekusanderu",
    "yomi_ink", "leozurcxxx"
]

# ====== Timeouts and Size Limits ======
API_TIMEOUT = 10            # seconds for API requests
MEDIA_CHECK_TIMEOUT = 10    # seconds for HEAD/GET to detect content type/length
DOWNLOAD_TIMEOUT = 30       # seconds for downloading media
MAX_PHOTO_SIZE = 10 * 1024 * 1024      # 10 MB for send_photo
MAX_UPLOAD_SIZE = 50 * 1024 * 1024     # 50 MB for uploads

# ====== Known chats for broadcasting ======
known_chats: set = set()

# ====== Allowed broadcaster user IDs ======
ALLOWED_BROADCASTERS = {5290407067, 7212116900, 7814187855, 7881890023, 7358752942}

# ====== Helper: send_action decorator ======
def send_action(action):
    """
    Decorator to send chat action before handler execution.
    """
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            try:
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=action)
            except Exception:
                pass
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator

# ====== Helper: Clean Rule34 Tag ======
def clean_rule34_tag(raw_tag: str) -> str:
    # Remove parentheses content, replace dots/spaces, lower-case
    t = re.sub(r'.*?', '', raw_tag)
    t = t.replace('.', '_').replace(' ', '_')
    t = t.strip(' _')
    return t.lower()

# ====== Async Helper: Fetch SFW image from Waifu.pics ======
async def fetch_image(category: str) -> Optional[str]:
    global aiohttp_session
    if aiohttp_session is None:
        return None
    url = f"https://api.waifu.pics/sfw/{category}"
    try:
        async with SEMAPHORE_FETCH:
            async with aiohttp_session.get(url, timeout=ClientTimeout(total=API_TIMEOUT)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get('url')
    except asyncio.TimeoutError:
        logger.debug(f"Waifu.pics fetch timeout for '{category}'")
    except Exception as e:
        logger.debug(f"Waifu.pics fetch error for '{category}': {e}")
    return None

# ====== Async Helper: Fetch one Rule34 media via JSON API ======
async def fetch_rule34_media_once(cleaned_tag: str) -> Optional[str]:
    global aiohttp_session
    if aiohttp_session is None:
        return None
    encoded = quote_plus(cleaned_tag)
    url = f"https://api.rule34.xxx/index.php?page=dapi&s=post&q=index&tags={encoded}&limit=100&json=1"
    try:
        async with SEMAPHORE_FETCH:
            async with aiohttp_session.get(url, timeout=ClientTimeout(total=API_TIMEOUT)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
    except asyncio.TimeoutError:
        logger.debug(f"Rule34 fetch timeout for tag '{cleaned_tag}'")
        return None
    except Exception as e:
        logger.debug(f"Rule34 fetch error for tag '{cleaned_tag}': {e}")
        return None
    if not isinstance(data, list) or not data:
        return None
    choice = random.choice(data)
    return choice.get("file_url")

# ====== Async Helper: Fetch Rule34 media of specific extensions via JSON API ======
async def fetch_rule34_media_once_of_type(cleaned_tag: str, ext_list: List[str]) -> List[str]:
    global aiohttp_session
    if aiohttp_session is None:
        return []
    encoded = quote_plus(cleaned_tag)
    url = f"https://api.rule34.xxx/index.php?page=dapi&s=post&q=index&tags={encoded}&limit=100&json=1"
    try:
        async with SEMAPHORE_FETCH:
            async with aiohttp_session.get(url, timeout=ClientTimeout(total=API_TIMEOUT)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
    except asyncio.TimeoutError:
        logger.debug(f"Rule34 fetch timeout for tag '{cleaned_tag}'")
        return []
    except Exception as e:
        logger.debug(f"Rule34 fetch error for tag '{cleaned_tag}': {e}")
        return []
    if not isinstance(data, list) or not data:
        return []
    candidates = []
    for post in data:
        file_url = post.get("file_url", "")
        lower = file_url.lower()
        for ext in ext_list:
            if lower.endswith(ext):
                candidates.append(file_url)
                break
    return candidates

# ====== Async Helper: Detect media info (type + length) ======
async def detect_media_info(url: str) -> Tuple[str, Optional[int]]:
    global aiohttp_session
    if aiohttp_session is None:
        return "", None
    # Try HEAD first
    try:
        async with SEMAPHORE_FETCH:
            async with aiohttp_session.head(url, timeout=ClientTimeout(total=MEDIA_CHECK_TIMEOUT), allow_redirects=True) as resp:
                ctype = resp.headers.get("Content-Type", "")
                clen = resp.headers.get("Content-Length")
                content_type = ctype.split(";")[0].strip().lower() if ctype else ""
                content_length = int(clen) if clen and clen.isdigit() else None
                if content_type or content_length is not None:
                    return content_type, content_length
    except Exception:
        pass
    # Fallback GET (only headers)
    try:
        async with SEMAPHORE_FETCH:
            async with aiohttp_session.get(url, timeout=ClientTimeout(total=MEDIA_CHECK_TIMEOUT), allow_redirects=True) as resp:
                ctype = resp.headers.get("Content-Type", "")
                clen = resp.headers.get("Content-Length")
                content_type = ctype.split(";")[0].strip().lower() if ctype else ""
                content_length = int(clen) if clen and clen.isdigit() else None
                return content_type, content_length
    except Exception:
        pass
    return "", None

# ====== Async Helper: Download media into BytesIO ======
async def download_media_to_bytesio(url: str, max_bytes: Optional[int] = None) -> Optional[BytesIO]:
    global aiohttp_session
    if aiohttp_session is None:
        return None
    try:
        async with SEMAPHORE_DOWNLOAD:
            async with aiohttp_session.get(url, timeout=ClientTimeout(total=DOWNLOAD_TIMEOUT), allow_redirects=True) as resp:
                resp.raise_for_status()
                bio = BytesIO()
                total = 0
                async for chunk in resp.content.iter_chunked(8192):
                    if not chunk:
                        break
                    total += len(chunk)
                    if max_bytes is not None and total > max_bytes:
                        return None
                    bio.write(chunk)
                # Name the BytesIO
                parsed = urlparse(url)
                filename = os.path.basename(parsed.path)
                if '.' in filename:
                    bio.name = filename
                else:
                    ctype = resp.headers.get("Content-Type", "")
                    subtype = None
                    if ctype:
                        parts = ctype.split(";")[0].split("/")
                        if len(parts) == 2:
                            subtype = parts[1].lower()
                    if subtype:
                        ext = subtype if subtype != 'jpeg' else 'jpg'
                        bio.name = f"file.{ext}"
                    else:
                        bio.name = "file"
                bio.seek(0)
                return bio
    except (asyncio.TimeoutError, ClientResponseError) as e:
        logger.debug(f"Download error for {url}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Download unexpected error for {url}: {e}")
        return None

# ====== Job DataClasses ======
@dataclass
class VideoJob:
    chat_id: int
    bot: object

@dataclass
class GifJob:
    chat_id: int
    bot: object

@dataclass
class PhotoJob:
    chat_id: int
    bot: object

@dataclass
class NsfwJob:
    chat_id: int
    bot: object

# ====== Queues and Worker Counts ======
video_queue: asyncio.Queue[VideoJob] = asyncio.Queue()
gif_queue: asyncio.Queue[GifJob] = asyncio.Queue()
photo_queue: asyncio.Queue[PhotoJob] = asyncio.Queue()
nsfw_queue: asyncio.Queue[NsfwJob] = asyncio.Queue()

VIDEO_WORKERS = 5
GIF_WORKERS = 5
PHOTO_WORKERS = 5
NSFW_WORKERS = 5

# ====== /start Command Handler (Kushina style) ======
@send_action(ChatAction.TYPING)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    chat_id = update.effective_chat.id
    user = update.effective_user

    # Record chat_id for broadcasting
    known_chats.add(chat_id)

    # Mention the user
    user_mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

    # Send typing action
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Keyboard buttons
    keyboard = [
        [
            InlineKeyboardButton('Updates', url=CHANNEL_LINK),
            InlineKeyboardButton('Support', url=GROUP_LINK)
        ],
        [
            InlineKeyboardButton('Add Me To Your Group', url=f'https://t.me/{context.bot.username}?startgroup=true')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Welcome text in first-person as Kushina Uzumaki
    welcome_text = (
        f"<b>👋 Hello {user_mention}, I’m Kushina Uzumaki!</b>\n\n"
        "<i>Full of fiery spirit and always eager to help, I share anime images to brighten your day!</i>\n\n"
        f"• Send <code>/help</code> to see all my commands.\n"
        "• I work in private chats or groups—ready for fun anytime.\n\n"
        "<b>🔥 Invite me to your group so everyone can join the excitement!</b>"
    )

    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode="HTML",
        disable_web_page_preview=True
    )

# ====== /help Command Handler (Kushina style) ======
@send_action(ChatAction.TYPING)
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    chat_id = update.effective_chat.id

    # Record chat_id for broadcasting
    known_chats.add(chat_id)

    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    sfw_descs = {
        'waifu': "💖 Cute waifu",
        'neko': "🐾 Catgirl",
        'shinobu': "🍩 Shinobu",
        'megumin': "💥 Megumin",
        'bully': "😈 Playful tease",
        'cuddle': "🤗 Warm cuddle",
        'cry': "😢 Emotional tears",
        'hug': "🤗 Gentle hug",
        'awoo': "🐺 Awoo",
        'kiss': "😘 Soft kiss",
        'lick': "👅 Playful lick",
        'pat': "🐾 Gentle pat",
        'smug': "😉 Cheeky smirk",
        'bonk': "🔨 Fun bonk",
        'yeet': "🌀 Yeet energy",
        'blush': "😊 Shy blush",
        'smile': "😄 Bright smile",
        'wave': "👋 Friendly wave",
        'highfive': "✋ High-five",
        'handhold': "🤝 Holding hands",
        'nom': "🍴 Yummy nom",
        'bite': "🦷 Playful bite",
        'slap': "👊 Dramatic slap",
        'kill': "💀 Intense scene",
        'kick': "👢 Strong kick",
        'happy': "😁 Joyful moment",
        'wink': "😉 Sweet wink",
        'poke': "👆 Gentle poke",
        'dance': "💃 Happy dance",
        'cringe': "😅 Funny cringe"
    }

    help_lines = [
        "<b>📖 Kushina Commands</b>",
        "",
        "<i>Hey there! I’m <b>Kushina Uzumaki</b>—full of energy and always eager to help!</i>",
        "<i>Send one of these commands and I’ll bring you an awesome anime image:</i>",
        ""
    ]
    for cmd, desc in sfw_descs.items():
        help_lines.append(f"• <code>/{cmd}</code> — <b>{desc}</b>")

    help_lines += [
        "",
        "<i>🤝 Invite me to your group so everyone can join the fun!</i>",
        "<i>📩 Or chat with me privately—I’m always excited to help!</i>",
        "",
        "<b>Stay spirited and enjoy these images! Believe it! 🔥</b>"
    ]

    help_text = "\n".join(help_lines)

    await update.message.reply_text(
        help_text,
        parse_mode="HTML",
        disable_web_page_preview=True
    )

# ====== Register Handlers ======
def register_category_handlers(app):
    # SFW handlers
    for category in SFW_CATEGORIES:
        async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE, cat=category):
            bot = context.bot
            chat_id = update.effective_chat.id

            # Record chat_id for broadcasting
            known_chats.add(chat_id)

            cd = context.chat_data
            sent_sfw = cd.setdefault('sent_sfw', {})
            dq: deque = sent_sfw.setdefault(cat, deque(maxlen=100))

            while True:
                url = await fetch_image(cat)
                if not url:
                    logger.warning(f"SFW /{cat}: fetch_image returned None; retrying.")
                    continue
                if url in dq:
                    logger.info(f"SFW /{cat}: URL already sent recently; fetching another.")
                    continue

                content_type, content_length = await detect_media_info(url)
                logger.info(f"SFW /{cat}: candidate url={url}, type={content_type}, length={content_length}")

                if not content_type.startswith("image/"):
                    logger.info(f"SFW /{cat}: content_type {content_type} not image/, skipping.")
                    dq.append(url)
                    continue

                if content_length is not None:
                    if content_length > MAX_UPLOAD_SIZE:
                        logger.info(f"SFW /{cat}: content_length {content_length} > MAX_UPLOAD_SIZE, skipping.")
                        dq.append(url)
                        continue
                else:
                    bio = await download_media_to_bytesio(url, MAX_UPLOAD_SIZE)
                    if not bio:
                        logger.info(f"SFW /{cat}: download_media_to_bytesio failed or >{MAX_UPLOAD_SIZE}, skipping.")
                        dq.append(url)
                        continue
                    try:
                        size = bio.getbuffer().nbytes
                        if size <= MAX_PHOTO_SIZE:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                            await update.message.reply_photo(bio)
                        else:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                            await update.message.reply_document(bio)
                        dq.append(url)
                        logger.info(f"SFW /{cat}: sent downloaded media successfully.")
                        break
                    except Exception as e:
                        logger.warning(f"SFW /{cat}: sending downloaded media failed: {e}; skipping URL.")
                        dq.append(url)
                        continue

                try:
                    subtype = content_type.split("/")[1]
                    if subtype == "gif" or url.lower().endswith(".gif"):
                        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                        await update.message.reply_animation(url)
                    else:
                        if content_length <= MAX_PHOTO_SIZE:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                            await update.message.reply_photo(url)
                        else:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                            await update.message.reply_document(url)
                    dq.append(url)
                    logger.info(f"SFW /{cat}: sent URL media successfully.")
                    break
                except BadRequest as e:
                    logger.warning(f"SFW /{cat}: BadRequest sending URL {url}: {e}; skipping URL.")
                    dq.append(url)
                    continue
                except Exception as e:
                    logger.warning(f"SFW /{cat}: Exception sending URL {url}: {e}, skipping URL.")
                    dq.append(url)
                    continue

        app.add_handler(CommandHandler(category, handler))

    # NSFW: /nsfw, /gif, /photo, /video with password gate (only in private)
    # /nsfw
    async def nsfw_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        chat_id = update.effective_chat.id

        # Record chat_id for broadcasting
        known_chats.add(chat_id)

        # Only in private
        if update.effective_chat.type != ChatType.PRIVATE:
            await update.message.reply_text("🤫 NSFW only in private chat.")
            return

        # If not unlocked yet, ask password
        if not context.user_data.get('nsfw_unlocked'):
            context.user_data['awaiting_nsfw_password'] = True
            await update.message.reply_text(
                "<i>Hehe, so curious about my hidden pleasures, aren’t you? 💗 Be a good little thing and ask my Asad for the secret. I only moan when he tells me to 💋💖</i>",
                parse_mode="HTML"
            )
            return

        # Already unlocked: enqueue job
        job = NsfwJob(chat_id=chat_id, bot=bot)
        try:
            nsfw_queue.put_nowait(job)
        except asyncio.QueueFull:
            await update.message.reply_text("⚠️ Busy right now. Please try again later.")

    app.add_handler(CommandHandler('nsfw', nsfw_handler))

    # /gif
    async def gif_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        chat_id = update.effective_chat.id

        known_chats.add(chat_id)

        if update.effective_chat.type != ChatType.PRIVATE:
            await update.message.reply_text("🤫 NSFW only in private chat.")
            return

        if not context.user_data.get('nsfw_unlocked'):
            context.user_data['awaiting_nsfw_password'] = True
            await update.message.reply_text(
                "<i>Hehe, you want to see my naughty side? 💕 Then ask my darling Asad for the secret phrase. I only open up for him 🫶</i>",
                parse_mode="HTML"
            )
            return

        job = GifJob(chat_id=chat_id, bot=bot)
        try:
            gif_queue.put_nowait(job)
        except asyncio.QueueFull:
            await update.message.reply_text("⚠️ Busy right now. Please try again later.")

    app.add_handler(CommandHandler('gif', gif_handler))

    # /photo
    async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        chat_id = update.effective_chat.id

        known_chats.add(chat_id)

        if update.effective_chat.type != ChatType.PRIVATE:
            await update.message.reply_text("🤫 NSFW only in private chat.")
            return

        if not context.user_data.get('nsfw_unlocked'):
            context.user_data['awaiting_nsfw_password'] = True
            await update.message.reply_text(
                "<i>Mmm, feeling bold, baby? 💘 Whisper the secret phrase to me, but only if Asad says you deserve it 💞🔥</i>",
                parse_mode="HTML"
            )
            return

        job = PhotoJob(chat_id=chat_id, bot=bot)
        try:
            photo_queue.put_nowait(job)
        except asyncio.QueueFull:
            await update.message.reply_text("⚠️ Busy right now. Please try again later.")

    app.add_handler(CommandHandler('photo', photo_handler))

    # /video
    async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        chat_id = update.effective_chat.id

        known_chats.add(chat_id)

        if update.effective_chat.type != ChatType.PRIVATE:
            await update.message.reply_text("🤫 NSFW only in private chat.")
            return

        if not context.user_data.get('nsfw_unlocked'):
            context.user_data['awaiting_nsfw_password'] = True
            await update.message.reply_text(
                "<i>Oh, craving something extra spicy from me? 💓 You better beg Asad for the magic words first. Kushina doesn’t tease for free 💦💝</i>",
                parse_mode="HTML"
            )
            return

        job = VideoJob(chat_id=chat_id, bot=bot)
        try:
            video_queue.put_nowait(job)
        except asyncio.QueueFull:
            await update.message.reply_text("⚠️ Busy right now. Please try again later.")

    app.add_handler(CommandHandler('video', video_handler))

    # Password entry handler for NSFW unlock
    async def nsfw_password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Only handle when awaiting password AND in private chat
        if update.effective_chat.type != ChatType.PRIVATE:
            return
        if not context.user_data.get('awaiting_nsfw_password'):
            return

        text = update.message.text.strip()
        # Correct secret phrase:
        if text == "ASAD LOVES RUPA":
            context.user_data['nsfw_unlocked'] = True
            context.user_data.pop('awaiting_nsfw_password', None)
            await update.message.reply_text(
                "<b>Ooh, so you know my secret already? 💖 That means you can play with my naughty side anytime you want 💦 Just don’t forget, Asad always gets first access 😉🔥</b>",
                parse_mode="HTML"
            )
        else:
            # Keep asking until correct; only triggered in private when awaiting
            await update.message.reply_text(
                "<i>Hmm… that’s not the phrase I was waiting for. Try again if you’re brave enough to handle me. But remember, only Asad truly knows how to unlock me 😉🫶</i>",
                parse_mode="HTML"
            )
        # Note: after correct, user must re-send the desired NSFW command.

    # Catch only plain text when awaiting_nsfw_password is True AND in private
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, nsfw_password_handler)
    )

    # /send broadcast command (secret; not added to command menu)
    async def send_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        chat_id = update.effective_chat.id

        known_chats.add(chat_id)

        user_id = user.id
        if user_id not in ALLOWED_BROADCASTERS:
            # Naughty pervy rejection
            await update.message.reply_text(
                "<i>Nice try, cutie. But only my Asad gets to press that button ❤️</i>",
                parse_mode="HTML"
            )
            return

        args = context.args
        if not args:
            await update.message.reply_text(
                "<i>Usage: <code>/send Your broadcast message here</code></i>",
                parse_mode="HTML"
            )
            return

        broadcast_text = " ".join(args)
        # Confirm to sender
        await update.message.reply_text(
            f"<b>Broadcasting to {len(known_chats)} chats...</b>",
            parse_mode="HTML"
        )
        success = 0
        fail = 0
        for cid in list(known_chats):
            try:
                await context.bot.send_message(
                    chat_id=cid,
                    text=broadcast_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                success += 1
            except Exception as e:
                logger.warning(f"Broadcast to {cid} failed: {e}")
                fail += 1
        await update.message.reply_text(
            f"<b>Broadcast completed:</b> sent to {success} chats, failed for {fail}.",
            parse_mode="HTML"
        )

    # Register send handler but do NOT add BotCommand for it in the menu
    app.add_handler(CommandHandler('send', send_broadcast_handler))


# ====== Worker Functions ======
async def nsfw_worker():
    global global_nsfw_history
    try:
        global_nsfw_history
    except NameError:
        global_nsfw_history = {}
    while True:
        job: NsfwJob = await nsfw_queue.get()
        chat_id = job.chat_id
        bot = job.bot

        sent_set = global_nsfw_history.setdefault(chat_id, set())

        while True:
            raw_tag = random.choice(RAW_NSFW_TAGS)
            cleaned = clean_rule34_tag(raw_tag)
            if not cleaned:
                continue
            candidate_url = await fetch_rule34_media_once(cleaned)
            if not candidate_url:
                continue
            if candidate_url in sent_set:
                continue

            ctype, clen = await detect_media_info(candidate_url)
            logger.info(f"[nsfw_worker] candidate url={candidate_url}, type={ctype}, length={clen}")

            if not ctype.startswith("image/") and not ctype.startswith("video/"):
                sent_set.add(candidate_url)
                continue
            if clen is not None and clen > MAX_UPLOAD_SIZE:
                sent_set.add(candidate_url)
                continue

            use_bio = None
            if clen is None:
                bio = await download_media_to_bytesio(candidate_url, MAX_UPLOAD_SIZE)
                if not bio:
                    sent_set.add(candidate_url)
                    continue
                use_bio = bio

            sent = False
            try:
                if ctype.startswith("image/"):
                    subtype = ctype.split("/")[1] if "/" in ctype else ""
                    target = use_bio if use_bio is not None else candidate_url
                    if subtype == "gif" or (
                        isinstance(target, str) and target.lower().endswith(".gif")
                    ) or (
                        not isinstance(target, str) and target.name.lower().endswith(".gif")
                    ):
                        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                        if use_bio is not None:
                            await bot.send_animation(chat_id=chat_id, animation=use_bio)
                        else:
                            await bot.send_animation(chat_id=chat_id, animation=candidate_url)
                    else:
                        if use_bio is not None:
                            size = use_bio.getbuffer().nbytes
                            if size <= MAX_PHOTO_SIZE:
                                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                                await bot.send_photo(chat_id=chat_id, photo=use_bio)
                            else:
                                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                                await bot.send_document(chat_id=chat_id, document=use_bio)
                        else:
                            if clen <= MAX_PHOTO_SIZE:
                                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                                await bot.send_photo(chat_id=chat_id, photo=candidate_url)
                            else:
                                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                                await bot.send_document(chat_id=chat_id, document=candidate_url)
                    sent = True

                elif ctype.startswith("video/"):
                    if use_bio is None:
                        try:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                            await bot.send_video(chat_id=chat_id, video=candidate_url)
                            sent = True
                        except BadRequest as e:
                            logger.warning(f"[nsfw_worker] send_video BadRequest: {e}; trying document")
                            try:
                                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                                await bot.send_document(chat_id=chat_id, document=candidate_url)
                                sent = True
                            except Exception as e2:
                                logger.warning(f"[nsfw_worker] send_document also failed: {e2}")
                                sent = False
                        except Exception as e:
                            logger.warning(f"[nsfw_worker] send_video exception: {e}; trying document")
                            try:
                                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                                await bot.send_document(chat_id=chat_id, document=candidate_url)
                                sent = True
                            except Exception as e2:
                                logger.warning(f"[nsfw_worker] document send exception: {e2}")
                                sent = False
                    else:
                        try:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                            await bot.send_document(chat_id=chat_id, document=use_bio)
                            sent = True
                        except Exception as e:
                            logger.warning(f"[nsfw_worker] send downloaded video bio failed: {e}")
                            sent = False
                else:
                    sent = False
            except Exception as e:
                logger.warning(f"[nsfw_worker] sending candidate_url failed: {e}")

            if sent:
                sent_set.add(candidate_url)
                logger.info(f"[nsfw_worker] successfully sent {candidate_url} to chat {chat_id}")
                break
            else:
                sent_set.add(candidate_url)
                continue

        nsfw_queue.task_done()

async def gif_worker():
    global global_gif_history
    try:
        global_gif_history
    except NameError:
        global_gif_history = {}
    while True:
        job: GifJob = await gif_queue.get()
        chat_id = job.chat_id
        bot = job.bot

        sent_set = global_gif_history.setdefault(chat_id, set())

        while True:
            raw_tag = random.choice(GIF_TAGS)
            cleaned = clean_rule34_tag(raw_tag)
            if not cleaned:
                continue

            candidates = await fetch_rule34_media_once_of_type(cleaned, ['.gif'])
            if not candidates:
                continue

            random.shuffle(candidates)
            sent_success = False
            for candidate_url in candidates:
                if candidate_url in sent_set:
                    continue
                ctype, clen = await detect_media_info(candidate_url)
                if not ctype.startswith("image/") and not ctype.startswith("video/"):
                    sent_set.add(candidate_url)
                    continue
                if clen is not None and clen > MAX_UPLOAD_SIZE:
                    sent_set.add(candidate_url)
                    continue

                use_bio = None
                if clen is None:
                    bio = await download_media_to_bytesio(candidate_url, MAX_UPLOAD_SIZE)
                    if not bio:
                        sent_set.add(candidate_url)
                        continue
                    use_bio = bio

                try:
                    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                    if use_bio is not None:
                        await bot.send_animation(chat_id=chat_id, animation=use_bio)
                    else:
                        await bot.send_animation(chat_id=chat_id, animation=candidate_url)
                    sent_set.add(candidate_url)
                    logger.info(f"[gif_worker] successfully sent {candidate_url} to chat {chat_id}")
                    sent_success = True
                    break
                except BadRequest as e:
                    logger.warning(f"[gif_worker] BadRequest sending {candidate_url}: {e}, skipping.")
                except Exception as e:
                    logger.warning(f"[gif_worker] Exception sending {candidate_url}: {e}, skipping.")
                finally:
                    sent_set.add(candidate_url)

            if sent_success:
                gif_queue.task_done()
                break
            else:
                continue

async def photo_worker():
    global global_photo_history
    try:
        global_photo_history
    except NameError:
        global_photo_history = {}
    while True:
        job: PhotoJob = await photo_queue.get()
        chat_id = job.chat_id
        bot = job.bot

        sent_set = global_photo_history.setdefault(chat_id, set())

        while True:
            raw_tag = random.choice(PHOTO_TAGS)
            cleaned = clean_rule34_tag(raw_tag)
            if not cleaned:
                continue

            candidates = await fetch_rule34_media_once_of_type(cleaned, ['.jpg', '.jpeg', '.png', '.webp'])
            if not candidates:
                continue

            random.shuffle(candidates)
            sent_success = False
            for candidate_url in candidates:
                if candidate_url in sent_set:
                    continue
                ctype, clen = await detect_media_info(candidate_url)
                if not ctype.startswith("image/"):
                    sent_set.add(candidate_url)
                    continue
                if clen is not None and clen > MAX_UPLOAD_SIZE:
                    sent_set.add(candidate_url)
                    continue

                use_bio = None
                if clen is None:
                    bio = await download_media_to_bytesio(candidate_url, MAX_UPLOAD_SIZE)
                    if not bio:
                        sent_set.add(candidate_url)
                        continue
                    use_bio = bio

                try:
                    if use_bio is not None:
                        size = use_bio.getbuffer().nbytes
                        if size <= MAX_PHOTO_SIZE:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                            await bot.send_photo(chat_id=chat_id, photo=use_bio)
                        else:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                            await bot.send_document(chat_id=chat_id, document=use_bio)
                    else:
                        if clen <= MAX_PHOTO_SIZE:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                            await bot.send_photo(chat_id=chat_id, photo=candidate_url)
                        else:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                            await bot.send_document(chat_id=chat_id, document=candidate_url)
                    sent_set.add(candidate_url)
                    logger.info(f"[photo_worker] successfully sent {candidate_url} to chat {chat_id}")
                    sent_success = True
                    break
                except BadRequest as e:
                    logger.warning(f"[photo_worker] BadRequest sending {candidate_url}: {e}, skipping.")
                except Exception as e:
                    logger.warning(f"[photo_worker] Exception sending {candidate_url}: {e}, skipping.")
                finally:
                    sent_set.add(candidate_url)

            if sent_success:
                photo_queue.task_done()
                break
            else:
                continue

async def video_worker():
    global global_video_history
    try:
        global_video_history
    except NameError:
        global_video_history = {}
    while True:
        job: VideoJob = await video_queue.get()
        chat_id = job.chat_id
        bot = job.bot

        sent_set = global_video_history.setdefault(chat_id, set())

        while True:
            tags_shuffled = VIDEO_TAGS.copy()
            random.shuffle(tags_shuffled)
            found_and_sent = False

            for raw_tag in tags_shuffled:
                cleaned = clean_rule34_tag(raw_tag)
                if not cleaned:
                    continue
                candidates = await fetch_rule34_media_once_of_type(cleaned, ['.mp4', '.webm', '.mov', '.mkv'])
                if not candidates:
                    continue
                random.shuffle(candidates)
                for candidate_url in candidates:
                    if candidate_url in sent_set:
                        continue
                    ctype, clen = await detect_media_info(candidate_url)
                    if not ctype.startswith("video/"):
                        sent_set.add(candidate_url)
                        continue
                    if clen is not None and clen > MAX_UPLOAD_SIZE:
                        sent_set.add(candidate_url)
                        continue

                    use_bio = None
                    if clen is None:
                        bio = await download_media_to_bytesio(candidate_url, MAX_UPLOAD_SIZE)
                        if not bio:
                            sent_set.add(candidate_url)
                            continue
                        use_bio = bio

                    try:
                        if use_bio is None:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                            await bot.send_video(chat_id=chat_id, video=candidate_url)
                        else:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                            await bot.send_document(chat_id=chat_id, document=use_bio)
                        sent_set.add(candidate_url)
                        logger.info(f"[video_worker] successfully sent {candidate_url} to chat {chat_id}")
                        found_and_sent = True
                        break
                    except BadRequest as e:
                        logger.warning(f"[video_worker] BadRequest sending {candidate_url}: {e}, skipping.")
                        sent_set.add(candidate_url)
                        continue
                    except Exception as e:
                        logger.warning(f"[video_worker] Exception sending {candidate_url}: {e}, skipping.")
                        sent_set.add(candidate_url)
                        continue

                if found_and_sent:
                    break

            if found_and_sent:
                video_queue.task_done()
                break
            else:
                logger.info("[video_worker] no viable video in this pass; clearing history and retrying.")
                sent_set.clear()
                continue

# ====== Global Error Handler ======
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception in handler: {context.error}", exc_info=True)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("😕 An unexpected error occurred.")
    except Exception:
        pass

# ====== Setup Bot Commands ======
async def setup_bot_commands(app):
    # Note: /send is NOT registered here, so it stays secret
    commands = [
        BotCommand('start', 'Start the bot'),
        BotCommand('help', 'Show help message'),
    ]
    for cat in SFW_CATEGORIES:
        commands.append(BotCommand(cat, f'Get a random {cat} image'))
    # NSFW commands appear but require unlock in private:
    commands.append(BotCommand('nsfw', 'Get a random NSFW media'))
    commands.append(BotCommand('photo', 'Get a random NSFW photo'))
    commands.append(BotCommand('gif', 'Get a random NSFW GIF'))
    commands.append(BotCommand('video', 'Get a random NSFW video'))
    # Do NOT include /send here.

    await app.bot.set_my_commands(commands)
    logger.info("Bot commands set (excluding /send).")

# ====== Main Runner ======
async def main():
    global aiohttp_session

    # Start dummy HTTP server thread for Render health checks
    threading.Thread(target=start_dummy_server, daemon=True).start()

    # 1. Create aiohttp session
    timeout = ClientTimeout(total=None)
    aiohttp_session = aiohttp.ClientSession(timeout=timeout)

    # 2. Build application
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 3. Register handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    register_category_handlers(app)
    app.add_error_handler(error_handler)
    await setup_bot_commands(app)

    # 4. Start worker tasks
    for _ in range(NSFW_WORKERS):
        asyncio.create_task(nsfw_worker())
    for _ in range(GIF_WORKERS):
        asyncio.create_task(gif_worker())
    for _ in range(PHOTO_WORKERS):
        asyncio.create_task(photo_worker())
    for _ in range(VIDEO_WORKERS):
        asyncio.create_task(video_worker())

    logger.info("💞 Kushina Sexy Baby Is Now Ready To Be Fucked So Hard.")

    # 5. Initialize and start application
    await app.initialize()
    await app.start()

    # 6. Start polling
    await app.updater.start_polling()

    # 7. Block forever until cancelled (SIGINT/SIGTERM)
    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass

    # 8. Shutdown sequence
    logger.info("Shutting down bot...")
    await app.updater.stop_polling()
    await app.stop()
    await app.shutdown()

    # 9. Close aiohttp session
    if aiohttp_session:
        await aiohttp_session.close()
        aiohttp_session = None

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass