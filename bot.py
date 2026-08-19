"""
HOLLY LIQUID — Telegram-бот + Mini App для прийому замовлень з доставкою InPost.
Тримовний: українська / польська / англійська (як на сайті).

Як це працює:
1. Клієнт натискає /start у боті.
2. Бот показує кнопку "🛒 Відкрити магазин" — вона відкриває сайт
   (Mini App) прямо всередині Telegram.
3. Клієнт обирає товари, оформлює кошик, вписує ПІБ/телефон/пачкомат
   прямо на сайті, і тисне "Надіслати замовлення" — весь кошик і дані
   автоматично приходять сюди, в бота (через Telegram.WebApp.sendData).
4. Бот показує клієнту зведення замовлення і реквізити BLIK.
5. Клієнт оплачує сам через свій додаток BLIK, тисне "Оплатив" і
   надсилає скрін — бот пересилає все адміну (товари, дані клієнта, скрін).

Режим роботи: WEBHOOK (не polling).
Telegram сам надсилає повідомлення боту, тому бот працює як звичайний
веб-сервіс — це дозволяє хостити його БЕЗКОШТОВНО на Render.com.

Запуск локально:
  pip install -r requirements.txt
  python bot.py

Обов'язково задайте змінні середовища:
  BOT_TOKEN        — токен бота від @BotFather
  ADMIN_CHAT_ID    — ваш Telegram chat_id, куди приходитимуть замовлення
  BLIK_PHONE       — номер телефону для BLIK-переказу
  WEBAPP_URL       — HTTPS-адреса САЙТУ (Mini App), напр. https://user.github.io/holyliquid/
  BASE_WEBHOOK_URL — HTTPS-адреса самого БОТА на Render,
                     напр. https://holyliquid-bot.onrender.com

Налаштування Mini App у @BotFather:
  /mybots → оберіть бота → Bot Settings → Menu Button → Configure Menu Button
  Вкажіть той самий WEBAPP_URL — тоді кнопка меню бота теж відкриватиме магазин.
"""

import json
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    WebAppInfo,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# ---------------------------------------------------------------------------
# CONFIG — заповніть тут або через змінні середовища
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВСТАВТЕ_СЮДИ_ТОКЕН_ВІД_BOTFATHER")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "ВСТАВТЕ_СЮДИ_ВАШ_CHAT_ID")
BLIK_PHONE = os.environ.get("BLIK_PHONE", "ХХХ ХХХ ХХХ (номер уточнюється)")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://ВСТАВТЕ_СЮДИ_АДРЕСУ_САЙТУ/")

# --- Налаштування webhook (для безкоштовного хостингу на Render) ---
# BASE_WEBHOOK_URL — публічна адреса самого БОТА на Render,
# наприклад https://holyliquid-bot.onrender.com
# На Render її видно у верхній частині сторінки сервісу після створення.
BASE_WEBHOOK_URL = os.environ.get("BASE_WEBHOOK_URL", "")
# Секретний шлях, щоб ніхто сторонній не міг надсилати боту фейкові запити.
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
# Render сам передає номер порту через змінну PORT — не змінюйте це.
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("holyliquid_bot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# ---------------------------------------------------------------------------
# I18N — тексти трьома мовами
# ---------------------------------------------------------------------------

TEXTS = {
    "ua": {
        "welcome": (
            "💥 <b>HOLLY LIQUID!</b> 💥\n\n"
            "Вітаємо! Тисни кнопку нижче, щоб відкрити магазин "
            "і оформити замовлення прямо тут, у Telegram:"
        ),
        "open_shop_button": "🛒 Відкрити магазин",
        "order_received": (
            "🧾 <b>Замовлення отримано!</b>\n\n"
            "{items}\n"
            "💰 Сума: <b>{total} zł</b>\n\n"
            "👤 {name}\n"
            "📞 {phone}\n"
            "📦 InPost: {point}\n\n"
            "💳 <b>Оплата через BLIK</b>\n"
            "Переведіть <b>{total} zł</b> на номер:\n"
            "<code>{blik}</code>\n\n"
            "Після оплати натисніть кнопку нижче або надішліть скрін підтвердження."
        ),
        "payment_button": "✅ Оплату надіслано",
        "payment_ack_callback": "Дякуємо! Замовлення передано адміністратору.",
        "final_photo": (
            "✅ Дякуємо! Скрін оплати та замовлення передано адміністратору.\n"
            "Ми зв'яжемося з вами найближчим часом для підтвердження.\n\n"
            "🎉 Дякую за замовлення!\n"
            "Holly Liquid — твій найкращий вибір"
        ),
        "final_button": (
            "✅ Дякуємо! Замовлення передано адміністратору.\n"
            "Ми зв'яжемося з вами найближчим часом для підтвердження оплати та доставки.\n\n"
            "🎉 Дякую за замовлення!\n"
            "Holly Liquid — твій найкращий вибір"
        ),
        "fallback": "Привіт! Щоб оформити замовлення, натисніть /start.",
        "invalid_data": "Не вдалося прочитати замовлення. Спробуйте оформити ще раз через магазин.",
    },
    "pl": {
        "welcome": (
            "💥 <b>HOLLY LIQUID!</b> 💥\n\n"
            "Witaj! Kliknij przycisk poniżej, aby otworzyć sklep "
            "i złożyć zamówienie prosto tutaj, w Telegramie:"
        ),
        "open_shop_button": "🛒 Otwórz sklep",
        "order_received": (
            "🧾 <b>Zamówienie otrzymane!</b>\n\n"
            "{items}\n"
            "💰 Suma: <b>{total} zł</b>\n\n"
            "👤 {name}\n"
            "📞 {phone}\n"
            "📦 InPost: {point}\n\n"
            "💳 <b>Płatność BLIK</b>\n"
            "Przelej <b>{total} zł</b> na numer:\n"
            "<code>{blik}</code>\n\n"
            "Po opłaceniu kliknij przycisk poniżej lub wyślij zrzut ekranu potwierdzający."
        ),
        "payment_button": "✅ Płatność wysłana",
        "payment_ack_callback": "Dziękujemy! Zamówienie przekazano administratorowi.",
        "final_photo": (
            "✅ Dziękujemy! Zrzut ekranu i zamówienie przekazano administratorowi.\n"
            "Skontaktujemy się wkrótce w celu potwierdzenia.\n\n"
            "🎉 Dziękujemy za zamówienie!\n"
            "Holly Liquid — twój najlepszy wybór"
        ),
        "final_button": (
            "✅ Dziękujemy! Zamówienie przekazano administratorowi.\n"
            "Skontaktujemy się wkrótce w celu potwierdzenia płatności i dostawy.\n\n"
            "🎉 Dziękujemy za zamówienie!\n"
            "Holly Liquid — twój najlepszy wybór"
        ),
        "fallback": "Cześć! Aby złożyć zamówienie, napisz /start.",
        "invalid_data": "Nie udało się odczytać zamówienia. Spróbuj ponownie przez sklep.",
    },
    "en": {
        "welcome": (
            "💥 <b>HOLLY LIQUID!</b> 💥\n\n"
            "Hi! Tap the button below to open the shop "
            "and place your order right here in Telegram:"
        ),
        "open_shop_button": "🛒 Open shop",
        "order_received": (
            "🧾 <b>Order received!</b>\n\n"
            "{items}\n"
            "💰 Total: <b>{total} zł</b>\n\n"
            "👤 {name}\n"
            "📞 {phone}\n"
            "📦 InPost: {point}\n\n"
            "💳 <b>BLIK payment</b>\n"
            "Transfer <b>{total} zł</b> to number:\n"
            "<code>{blik}</code>\n\n"
            "After paying, tap the button below or send a payment screenshot."
        ),
        "payment_button": "✅ Payment sent",
        "payment_ack_callback": "Thank you! Order sent to the admin.",
        "final_photo": (
            "✅ Thank you! Payment screenshot and order sent to the admin.\n"
            "We'll contact you shortly to confirm.\n\n"
            "🎉 Thank you for your order!\n"
            "Holly Liquid — your best choice"
        ),
        "final_button": (
            "✅ Thank you! Order sent to the admin.\n"
            "We'll contact you shortly to confirm payment and delivery.\n\n"
            "🎉 Thank you for your order!\n"
            "Holly Liquid — your best choice"
        ),
        "fallback": "Hi! To place an order, type /start.",
        "invalid_data": "Couldn't read the order. Please try again through the shop.",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in TEXTS else "ua"
    template = TEXTS[lang].get(key, TEXTS["ua"].get(key, ""))
    return template.format(**kwargs) if kwargs else template


# ---------------------------------------------------------------------------
# STATES
# ---------------------------------------------------------------------------

class OrderForm(StatesGroup):
    waiting_payment_proof = State()


# ---------------------------------------------------------------------------
# KEYBOARDS
# ---------------------------------------------------------------------------

def open_shop_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "open_shop_button"), web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
    )


def confirm_payment_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "payment_button"), callback_data="payment_sent")]
        ]
    )


# ---------------------------------------------------------------------------
# HANDLERS
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    lang = (message.from_user.language_code or "ua")[:2]
    if lang not in TEXTS:
        lang = "ua"
    await state.update_data(lang=lang)

    await message.answer(
        t(lang, "welcome"),
        parse_mode="HTML",
        reply_markup=open_shop_keyboard(lang),
    )


@router.message(F.web_app_data)
async def process_webapp_data(message: Message, state: FSMContext):
    """
    Called when the Mini App sends data via Telegram.WebApp.sendData().
    Expected JSON payload (produced by the site's checkout flow):
    {
      "items": [{"name": "Cola", "brand": "ELFLIQ 30ml 5%", "qty": 2, "price": 50}, ...],
      "total": 150,
      "name": "Roman Example",
      "phone": "+48123456789",
      "point": "WAW01A",
      "lang": "ua"
    }
    """
    data_state = await state.get_data()
    lang = data_state.get("lang", "ua")

    try:
        payload = json.loads(message.web_app_data.data)
    except (ValueError, AttributeError) as e:
        logger.error(f"Failed to parse WebApp data: {e}")
        await message.answer(t(lang, "invalid_data"), reply_markup=open_shop_keyboard(lang))
        return

    lang = payload.get("lang", lang)
    if lang not in TEXTS:
        lang = "ua"

    items = payload.get("items", [])
    total = payload.get("total", 0)
    name = payload.get("name", "—")
    phone = payload.get("phone", "—")
    point = payload.get("point", "—")

    items_text = "\n".join(
        f"• {it.get('name', '—')} ({it.get('brand', '—')}) x{it.get('qty', 1)}"
        for it in items
    ) or "—"

    await state.update_data(
        lang=lang,
        items=items,
        total=total,
        name=name,
        phone=phone,
        point=point,
    )

    order_text = t(
        lang,
        "order_received",
        items=items_text,
        total=total,
        name=name,
        phone=phone,
        point=point,
        blik=BLIK_PHONE,
    )
    await message.answer(
        order_text,
        parse_mode="HTML",
        reply_markup=confirm_payment_keyboard(lang),
    )
    await state.set_state(OrderForm.waiting_payment_proof)

    # Notify admin immediately that an order came in (without payment proof yet)
    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=build_admin_order_text(await state.get_data(), message.from_user, note="🕐 Очікує підтвердження оплати."),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to notify admin about new order: {e}")


@router.callback_query(F.data == "payment_sent")
async def payment_confirmed_button(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ua")
    await finalize_order(callback.message, state, lang, proof_note="✅ Клієнт підтвердив оплату кнопкою.")
    await callback.answer(t(lang, "payment_ack_callback"))


@router.message(OrderForm.waiting_payment_proof, F.photo)
async def payment_proof_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ua")

    caption = build_admin_order_text(data, message.from_user, note="📸 Клієнт надіслав скрін оплати.")
    try:
        await bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=message.photo[-1].file_id,
            caption=caption,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

    await message.answer(t(lang, "final_photo"), reply_markup=open_shop_keyboard(lang))
    await state.clear()


async def finalize_order(message: Message, state: FSMContext, lang: str, proof_note: str = ""):
    data = await state.get_data()
    text = build_admin_order_text(data, message.chat, proof_note)
    try:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

    await message.answer(t(lang, "final_button"), reply_markup=open_shop_keyboard(lang))
    await state.clear()


def build_admin_order_text(data: dict, user, note: str = "") -> str:
    username = getattr(user, "username", None)
    user_link = f"@{username}" if username else "немає username"
    lang_label = {"ua": "🇺🇦 UA", "pl": "🇵🇱 PL", "en": "🇬🇧 EN"}.get(data.get("lang", "ua"), "—")

    items = data.get("items", [])
    items_text = "\n".join(
        f"• {it.get('name', '—')} ({it.get('brand', '—')}) x{it.get('qty', 1)}"
        for it in items
    ) or "—"

    return (
        "🔔 <b>Нове замовлення HOLLY LIQUID!</b>\n\n"
        f"Мова клієнта: {lang_label}\n\n"
        f"{items_text}\n\n"
        f"Сума: <b>{data.get('total', '—')} zł</b>\n"
        f"Ім'я: {data.get('name', '—')}\n"
        f"Телефон: {data.get('phone', '—')}\n"
        f"InPost: {data.get('point', '—')}\n"
        f"Telegram клієнта: {user_link}\n"
        f"{note}\n"
        f"Час: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


@router.message()
async def fallback(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        data = await state.get_data()
        lang = data.get("lang", "ua")
        await message.answer(t(lang, "fallback"))


# ---------------------------------------------------------------------------
# ENTRYPOINT
# ---------------------------------------------------------------------------

async def on_startup(app: web.Application):
    """Реєструє webhook у Telegram при запуску сервісу."""
    if not BASE_WEBHOOK_URL:
        logger.error(
            "BASE_WEBHOOK_URL не задано! Впишіть адресу сервісу на Render "
            "у змінні середовища, інакше бот не отримуватиме повідомлення."
        )
        return
    webhook_url = BASE_WEBHOOK_URL.rstrip("/") + WEBHOOK_PATH
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info(f"Webhook встановлено: {webhook_url}")


async def on_shutdown(app: web.Application):
    """Акуратно прибирає webhook при зупинці."""
    await bot.delete_webhook()
    logger.info("Webhook видалено")


async def health(request: web.Request):
    """
    Проста сторінка-відповідь для Render.
    Render періодично перевіряє, чи сервіс живий — ця відповідь
    підтверджує, що все працює. Також сюди можна налаштувати
    зовнішній пінгер (UptimeRobot), щоб сервіс не засинав.
    """
    return web.Response(text="HOLLY LIQUID bot is running")


def main():
    logger.info("Starting HOLLY LIQUID bot (webhook mode)...")

    app = web.Application()
    app.router.add_get("/", health)

    # Підключаємо обробник, який приймає оновлення від Telegram
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
