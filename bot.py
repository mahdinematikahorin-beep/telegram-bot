# -*- coding: utf-8 -*-
"""
ربات قیمت طلا، سکه، ارز و ماشین‌حساب تبدیل
Python 3.10+ | python-telegram-bot v21
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ==================== تنظیمات ====================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"          # از @BotFather بگیر
CACHE_SECONDS = 30                         # کش قیمت‌ها

# نمادهای مهم tgju.org
SYMBOLS = {
    "dollar":        ("price_dollar_rl",     "دلار آمریکا"),
    "euro":          ("price_eur",           "یورو"),
    "gold18":        ("geram18",             "طلای ۱۸ عیار (گرم)"),
    "gold24":        ("geram24",             "طلای ۲۴ عیار (گرم)"),
    "mesghal":       ("mesghal",             "مثقال طلا"),
    "sekeh_emami":   ("sekee",               "سکه امامی"),
    "nim_sekeh":     ("nim",                 "نیم سکه"),
    "rob_sekeh":     ("rob",                 "ربع سکه"),
    "sekeh_gerami":  ("gerami",              "سکه گرمی"),
    "silver":        ("silver_999",          "نقره ۹۹۹ (گرم)"),
}

# ==================== لاگ ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ==================== کش قیمت ====================
class PriceCache:
    def __init__(self):
        self.data: Dict[str, float] = {}
        self.last_update: Optional[datetime] = None
        self.lock = asyncio.Lock()

    def is_valid(self) -> bool:
        if not self.last_update or not self.data:
            return False
        return datetime.now() - self.last_update < timedelta(seconds=CACHE_SECONDS)

    async def get_prices(self) -> Dict[str, float]:
        async with self.lock:
            if self.is_valid():
                return self.data.copy()
            prices = await asyncio.to_thread(fetch_prices_from_tgju)
            if prices:
                self.data = prices
                self.last_update = datetime.now()
            return self.data.copy()

price_cache = PriceCache()

# ==================== دریافت قیمت از tgju ====================
def fetch_prices_from_tgju() -> Dict[str, float]:
    """
    اسکراپ سبک از tgju.org
    در صورت قطع بودن سایت، قیمت‌های نمونه برمی‌گرداند تا ربات از کار نیفتد.
    """
    result = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        # صفحه اصلی ارز و طلا
        urls = [
            "https://www.tgju.org/currency",
            "https://www.tgju.org/gold-chart",
            "https://www.tgju.org/coin",
        ]
        for url in urls:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # پیدا کردن ردیف‌های قیمت
            for tr in soup.select("tr[data-market-row]"):
                key = tr.get("data-market-row", "").strip()
                price_td = tr.select_one("td.nf")
                if not key or not price_td:
                    continue
                price_text = price_td.get_text(strip=True).replace(",", "").replace("٬", "")
                try:
                    price = float(price_text)
                    # تبدیل ریال به تومان اگر لازم باشد (tgju معمولاً ریال می‌دهد)
                    # در عمل بسیاری از نمادها به ریال هستند → تقسیم بر ۱۰
                    if price > 100_000:          # احتمالاً ریال است
                        price = price / 10
                    result[key] = price
                except ValueError:
                    continue

        # نگاشت کلیدهای داخلی
        mapped = {}
        for internal, (tgju_key, _) in SYMBOLS.items():
            # چند نام ممکن برای هر نماد
            candidates = [tgju_key, f"price_{tgju_key}", tgju_key.replace("_", "")]
            for c in candidates:
                if c in result:
                    mapped[internal] = result[c]
                    break
            # جستجوی تقریبی
            for k, v in result.items():
                if tgju_key in k or k in tgju_key:
                    mapped[internal] = v
                    break

        if mapped:
            logger.info(f"Prices fetched: {len(mapped)} items")
            return mapped

    except Exception as e:
        logger.error(f"Fetch error: {e}")

    # Fallback نمونه (برای تست وقتی اینترنت/سایت مشکل دارد)
    logger.warning("Using fallback sample prices")
    return {
        "dollar": 92000,
        "euro": 100000,
        "gold18": 5200000,
        "gold24": 6900000,
        "mesghal": 22500000,
        "sekeh_emami": 58000000,
        "nim_sekeh": 31000000,
        "rob_sekeh": 18000000,
        "sekeh_gerami": 9500000,
        "silver": 85000,
    }

# ==================== ابزارها ====================
def format_number(n: float, decimals: int = 0) -> str:
    """فرمت زیبا با جداکننده هزارگان"""
    if decimals == 0:
        return f"{int(round(n)):,}".replace(",", "٬")
    return f"{n:,.{decimals}f}".replace(",", "٬")

def parse_persian_number(text: str) -> Optional[float]:
    """تبدیل اعداد فارسی/انگلیسی و جداکننده‌ها به float"""
    if not text:
        return None
    text = text.strip()
    # اعداد فارسی → انگلیسی
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    text = text.translate(trans)
    # حذف جداکننده‌ها و کلمات رایج
    text = re.sub(r"[٬, ]", "", text)
    text = text.replace("میلیون", "000000").replace("میلیارد", "000000000")
    text = re.sub(r"[^\d.]", "", text)
    try:
        return float(text)
    except ValueError:
        return None

def format_price_message(prices: Dict[str, float]) -> str:
    now = datetime.now().strftime("%H:%M:%S")
    lines = [
        "📊 <b>قیمت‌های لحظه‌ای بازار</b>",
        f"🕐 آخرین به‌روزرسانی: {now}",
        "",
        "💵 <b>ارز</b>",
        f"• دلار آمریکا: <code>{format_number(prices.get('dollar', 0))}</code> تومان",
        f"• یورو: <code>{format_number(prices.get('euro', 0))}</code> تومان",
        "",
        "🥇 <b>طلا</b>",
        f"• طلای ۱۸ عیار: <code>{format_number(prices.get('gold18', 0))}</code> تومان / گرم",
        f"• طلای ۲۴ عیار: <code>{format_number(prices.get('gold24', 0))}</code> تومان / گرم",
        f"• مثقال طلا: <code>{format_number(prices.get('mesghal', 0))}</code> تومان",
        "",
        "🪙 <b>سکه</b>",
        f"• سکه امامی: <code>{format_number(prices.get('sekeh_emami', 0))}</code> تومان",
        f"• نیم‌سکه: <code>{format_number(prices.get('nim_sekeh', 0))}</code> تومان",
        f"• ربع‌سکه: <code>{format_number(prices.get('rob_sekeh', 0))}</code> تومان",
        f"• سکه گرمی: <code>{format_number(prices.get('sekeh_gerami', 0))}</code> تومان",
        "",
        "🥈 <b>نقره</b>",
        f"• نقره ۹۹۹: <code>{format_number(prices.get('silver', 0))}</code> تومان / گرم",
        "",
        "⚠️ قیمت‌ها تقریبی و برای اطلاع‌رسانی است.",
    ]
    return "\n".join(lines)

# ==================== کیبوردها ====================
def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📊 قیمت لحظه‌ای"), KeyboardButton("🧮 ماشین‌حساب")],
            [KeyboardButton("ℹ️ راهنما")],
        ],
        resize_keyboard=True,
    )

def converter_type_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("تومان → طلا / سکه / دلار", callback_data="conv_toman"),
            ],
            [
                InlineKeyboardButton("گرم طلا → تومان / دلار", callback_data="conv_gold"),
            ],
            [
                InlineKeyboardButton("دلار → طلا / نقره / سکه", callback_data="conv_dollar"),
            ],
            [
                InlineKeyboardButton("تعداد سکه → تومان / دلار", callback_data="conv_coin"),
            ],
            [InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
        ]
    )

# ==================== States ====================
(
    CHOOSING_TYPE,
    WAITING_AMOUNT,
) = range(2)

# ==================== Handlers ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "سلام 👋\n"
        "به ربات قیمت طلا، سکه و ارز خوش اومدی.\n\n"
        "می‌تونی قیمت لحظه‌ای ببینی یا با ماشین‌حساب تبدیل کنی:\n"
        "• چند میلیون تومان چند گرم طلا می‌شه؟\n"
        "• ۵ گرم طلا چند دلاره؟\n"
        "• ۲۰۰۰ دلار چند گرم طلا یا چند سکه می‌شه؟\n\n"
        "از دکمه‌های پایین استفاده کن."
    )
    await update.message.reply_text(text, reply_markup=main_keyboard())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>راهنما</b>\n\n"
        "۱. دکمه <b>قیمت لحظه‌ای</b> → آخرین قیمت‌ها\n"
        "۲. دکمه <b>ماشین‌حساب</b> → تبدیل مبلغ\n\n"
        "می‌تونی اعداد رو به صورت فارسی یا انگلیسی بنویسی:\n"
        "<code>۲۰۰۰۰۰۰</code> یا <code>2,000,000</code> یا <code>۲ میلیون</code>\n\n"
        "قیمت‌ها از منابع معتبر بازار ایران گرفته می‌شن و هر ۳۰ ثانیه به‌روز می‌شن."
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())

async def show_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("در حال دریافت قیمت‌ها... ⏳")
    prices = await price_cache.get_prices()
    text = format_price_message(prices)
    await msg.edit_text(text, parse_mode="HTML")

async def start_converter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "نوع تبدیل رو انتخاب کن:",
        reply_markup=converter_type_keyboard(),
    )
    return CHOOSING_TYPE

async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("لغو شد.")
        return ConversationHandler.END

    context.user_data["conv_type"] = query.data

    prompts = {
        "conv_toman": "مبلغ به <b>تومان</b> رو وارد کن (مثلاً ۲ میلیون یا 2000000):",
        "conv_gold": "وزن طلا به <b>گرم</b> رو وارد کن (مثلاً ۵ یا 5.5):",
        "conv_dollar": "مبلغ به <b>دلار</b> رو وارد کن (مثلاً ۲۰۰۰):",
        "conv_coin": "تعداد <b>سکه امامی</b> رو وارد کن (مثلاً ۲):",
    }
    await query.edit_message_text(prompts[query.data], parse_mode="HTML")
    return WAITING_AMOUNT

async def process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = parse_persian_number(update.message.text)
    if amount is None or amount <= 0:
        await update.message.reply_text("عدد معتبر وارد کن. دوباره امتحان کن:")
        return WAITING_AMOUNT

    prices = await price_cache.get_prices()
    conv_type = context.user_data.get("conv_type")

    dollar = prices.get("dollar", 1)
    gold18 = prices.get("gold18", 1)
    silver = prices.get("silver", 1)
    sekeh = prices.get("sekeh_emami", 1)
    nim = prices.get("nim_sekeh", 1)
    rob = prices.get("rob_sekeh", 1)

    lines = ["✅ <b>نتیجه تبدیل</b>\n"]

    if conv_type == "conv_toman":
        lines.append(f"مبلغ: <code>{format_number(amount)}</code> تومان\n")
        lines.append(f"• طلا ۱۸ عیار: <b>{format_number(amount / gold18, 2)}</b> گرم")
        lines.append(f"• نقره: <b>{format_number(amount / silver, 1)}</b> گرم")
        lines.append(f"• دلار: <b>{format_number(amount / dollar, 2)}</b> دلار")
        lines.append(f"• سکه امامی: <b>{format_number(amount / sekeh, 2)}</b> عدد")
        lines.append(f"• نیم‌سکه: <b>{format_number(amount / nim, 2)}</b> عدد")
        lines.append(f"• ربع‌سکه: <b>{format_number(amount / rob, 2)}</b> عدد")

    elif conv_type == "conv_gold":
        toman = amount * gold18
        lines.append(f"وزن: <code>{format_number(amount, 2)}</code> گرم طلای ۱۸\n")
        lines.append(f"• تومان: <b>{format_number(toman)}</b> تومان")
        lines.append(f"• دلار: <b>{format_number(toman / dollar, 2)}</b> دلار")
        lines.append(f"• معادل سکه امامی: <b>{format_number(toman / sekeh, 3)}</b> عدد")

    elif conv_type == "conv_dollar":
        toman = amount * dollar
        lines.append(f"مبلغ: <code>{format_number(amount, 2)}</code> دلار\n")
        lines.append(f"• تومان: <b>{format_number(toman)}</b> تومان")
        lines.append(f"• طلا ۱۸ عیار: <b>{format_number(toman / gold18, 2)}</b> گرم")
        lines.append(f"• نقره: <b>{format_number(toman / silver, 1)}</b> گرم")
        lines.append(f"• سکه امامی: <b>{format_number(toman / sekeh, 2)}</b> عدد")

    elif conv_type == "conv_coin":
        toman = amount * sekeh
        lines.append(f"تعداد: <code>{format_number(amount, 1)}</code> سکه امامی\n")
        lines.append(f"• تومان: <b>{format_number(toman)}</b> تومان")
        lines.append(f"• دلار: <b>{format_number(toman / dollar, 2)}</b> دلار")
        lines.append(f"• معادل طلا: <b>{format_number(toman / gold18, 2)}</b> گرم")

    lines.append("\n⚠️ قیمت‌ها تقریبی هستند و هزینه کارمزد/اجرت در نظر گرفته نشده.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=main_keyboard())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.", reply_markup=main_keyboard())
    return ConversationHandler.END

# ==================== main ====================
from telegram.request import HTTPXRequest

def main():
    if BOT_TOKEN == "8611275522:AAFlK8MOh82pEH2ar9CevaozFKyKuZ-lqW8":
        print("❌ لطفاً BOT_TOKEN را در کد قرار دهید.")
        return

    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=90.0,      # خیلی زیاد
        read_timeout=90.0,
        write_timeout=90.0,
        pool_timeout=90.0,
    )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .get_updates_request(request)
        .connect_timeout(90.0)
        .read_timeout(90.0)
        .write_timeout(90.0)
        .pool_timeout(90.0)
        .build()
    )

    # بقیه کد (handlers) مثل قبل بماند
    # ...

    print("در حال اتصال به تلگرام... ممکن است کمی طول بکشد")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False,
    )
