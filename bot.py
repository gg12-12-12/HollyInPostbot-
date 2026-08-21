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

import asyncio
import json
import logging
import random
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
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

# Скільки хвилин чекати перед нагадуванням менеджеру про неоплачене замовлення.
PAYMENT_REMINDER_MINUTES = 15
# Через скільки хвилин без доказу оплати замовлення скасовується автоматично.
PAYMENT_AUTOCANCEL_MINUTES = 30

# Номери замовлень, по яких оплату вже підтвердили/скасували — щоб не
# надсилати зайве нагадування, якщо все вже вирішено. Живе тільки в пам'яті
# процесу (обнуляється при перезапуску Render — це прийнятно для нагадувань).
_resolved_orders: set[str] = set()


# ---------------------------------------------------------------------------
# I18N — тексти трьома мовами
# ---------------------------------------------------------------------------

TEXTS = {
    "ua": {
        "welcome": (
            "💥 <b>HOLLY LIQUID</b> 💥\n"
            "<i>Твій найкращий вибір</i>\n\n"

            "Це офіційний бот магазину — тут ти можеш переглянути весь "
            "асортимент і оформити замовлення з доставкою InPost по всій Польщі.\n\n"

            "<b>Як це працює:</b>\n\n"

            "1️⃣ Тисни <b>«🛒 Відкрити магазин»</b> внизу — каталог відкриється "
            "прямо тут, у Telegram\n\n"

            "2️⃣ Обери смаки й додай їх у кошик 🛒\n\n"

            "3️⃣ Натисни <b>«Оформити замовлення»</b> → <b>«📦 InPost»</b> "
            "і впиши ім'я, телефон та номер пачкомату\n\n"

            "4️⃣ Я одразу надішлю тобі суму й реквізити для оплати <b>BLIK</b>\n\n"

            "5️⃣ Після оплати надішли сюди скріншот — і замовлення піде в роботу 📦\n\n"

            "───────────────\n"
            "🚚 <b>Доставка:</b> InPost Пачкомат — 15 zł · Кур'єр — 25 zł\n"
            "💳 <b>Оплата:</b> BLIK, USDT або готівка при зустрічі\n"
            "🕐 <b>Працюємо:</b> Пн-Пт 6:00-23:00 · Сб-Нд 10:00-22:00\n"
            "───────────────\n\n"

            "❓ У разі питань, або якщо виникли будь-які проблеми "
            "із замовленням — звертайся до нашого менеджера "
            "@hollymollydeal, він завжди на звʼязку 🤝\n\n"

            "<b>Тисни кнопку нижче, щоб почати</b> 👇"
        ),
        "open_shop_button": "🛒 Відкрити магазин",
        "order_ack": "🧾 Замовлення отримано! Готую реквізити для оплати...",
        "cancel_order_button": "❌ Скасувати замовлення",
        "order_cancelled_client": "Замовлення скасовано. Якщо передумаєш — заходь знову через магазин 🛒",
        "order_cancelled_admin_note": "❌ Клієнт скасував замовлення.",
        "cancel_confirm_title": "Скасувати замовлення?",
        "cancel_confirm_message": "Замовлення {order_no} буде скасовано.",
        "cancel_confirm_yes": "Так, скасувати",
        "cancel_confirm_no": "Ні, залишити",
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
            "❗️Після оплати обов'язково надішліть сюди <b>скріншот або PDF-квитанцію</b> "
            "про переказ — без цього ми не зможемо підтвердити замовлення."
        ),
        "invalid_proof_format": (
            "Це не схоже на скрін чи квитанцію 🤔\n"
            "Надішли, будь ласка, фото екрана оплати або PDF-файл квитанції."
        ),
        "proof_required_reminder": (
            "Щоб підтвердити замовлення, надішли сюди <b>скріншот оплати</b> "
            "або <b>PDF-квитанцію</b> 📸📄"
        ),
        "order_autocancelled_client": (
            "⏰ Замовлення {order_no} скасовано автоматично — минуло 30 хв "
            "без підтвердження оплати.\n\n"
            "Якщо ти все ж оплатив(-ла) — просто оформи замовлення ще раз "
            "і одразу надішли скрін чи квитанцію 🙏"
        ),
        "quick_reply_delay": "🚚 Вибачте за затримку! Ваше замовлення {order_no} трохи затримується з відправкою, ми вже працюємо над цим і скоро воно вирушить.",
        "quick_reply_addr": "📍 Уточніть, будь ласка, точну адресу або номер пачкомату InPost для замовлення {order_no} — щоб ми могли надіслати посилку без затримок.",
        "quick_reply_thanks": "🙏 Дякуємо за замовлення {order_no}! Раді, що обрали HOLLY LIQUID 🖤",
        "quick_reply_sent_admin": "✅ Шаблон надіслано клієнту.",
        "payment_button": "✅ Оплату надіслано",
        "payment_ack_callback": "Дякуємо! Замовлення передано адміністратору.",
        "final_photo": (
            "✅ Дякуємо! Скрін оплати та замовлення передано адміністратору.\n"
            "Ми зв'яжемося з вами найближчим часом для підтвердження.\n\n"
            "❓ Виникли питання або проблеми? Пиши менеджеру @hollymollydeal\n\n"
            "🎉 Дякую за замовлення!\n"
            "Holly Liquid — твій найкращий вибір"
        ),
        "final_button": (
            "✅ Дякуємо! Замовлення передано адміністратору.\n"
            "Ми зв'яжемося з вами найближчим часом для підтвердження оплати та доставки.\n\n"
            "❓ Виникли питання або проблеми? Пиши менеджеру @hollymollydeal\n\n"
            "🎉 Дякую за замовлення!\n"
            "Holly Liquid — твій найкращий вибір"
        ),
        "fallback": (
            "Я приймаю замовлення через магазин 🛒\n\n"
            "Тисни кнопку <b>«🛒 Відкрити магазин»</b> внизу екрана, "
            "щоб обрати товари.\n\n"
            "Якщо кнопки не видно — напиши /start\n"
            "Інструкція ще раз — /help\n\n"
            "Питання до менеджера: @hollymollydeal"
        ),
        "invalid_data": "Не вдалося прочитати замовлення. Спробуйте оформити ще раз через магазин.",
        "order_no_label": "Номер замовлення",
        "payment_confirmed": (
            "✅ <b>Оплату зараховано!</b>\n\n"
            "Замовлення <b>{order_no}</b> прийнято в роботу.\n"
            "Ми пакуємо його та найближчим часом передамо в InPost.\n\n"
            "Дякуємо за замовлення! 🖤"
        ),
        "tracking_sent": (
            "📦 <b>Замовлення відправлено!</b>\n\n"
            "Замовлення: <b>{order_no}</b>\n"
            "Номер посилки InPost: <code>{tracking}</code>\n\n"
            "Відстежити: https://inpost.pl/sledzenie-przesylek\n\n"
            "Дякуємо, що обрали HOLLY LIQUID! 🖤"
        ),
    },
    "pl": {
        "welcome": (
            "💥 <b>HOLLY LIQUID</b> 💥\n"
            "<i>Twój najlepszy wybór</i>\n\n"

            "To oficjalny bot sklepu — tutaj obejrzysz cały asortyment "
            "i złożysz zamówienie z dostawą InPost na terenie całej Polski.\n\n"

            "<b>Jak to działa:</b>\n\n"

            "1️⃣ Kliknij <b>«🛒 Otwórz sklep»</b> na dole — katalog otworzy się "
            "bezpośrednio tutaj, w Telegramie\n\n"

            "2️⃣ Wybierz smaki i dodaj je do koszyka 🛒\n\n"

            "3️⃣ Kliknij <b>«Złóż zamówienie»</b> → <b>«📦 InPost»</b> "
            "i wpisz imię, telefon oraz numer paczkomatu\n\n"

            "4️⃣ Od razu wyślę Ci kwotę i dane do płatności <b>BLIK</b>\n\n"

            "5️⃣ Po opłaceniu wyślij tutaj zrzut ekranu — i zamówienie rusza 📦\n\n"

            "───────────────\n"
            "🚚 <b>Dostawa:</b> Paczkomat InPost — 15 zł · Kurier — 25 zł\n"
            "💳 <b>Płatność:</b> BLIK, USDT lub gotówka przy odbiorze\n"
            "🕐 <b>Godziny:</b> Pn-Pt 6:00-23:00 · Sb-Nd 10:00-22:00\n"
            "───────────────\n\n"

            "❓ W razie pytań lub jakichkolwiek problemów z zamówieniem "
            "skontaktuj się z naszym menedżerem @hollymollydeal — "
            "zawsze jest do dyspozycji 🤝\n\n"

            "<b>Kliknij przycisk poniżej, aby zacząć</b> 👇"
        ),
        "open_shop_button": "🛒 Otwórz sklep",
        "order_ack": "🧾 Zamówienie otrzymane! Przygotowuję dane do płatności...",
        "cancel_order_button": "❌ Anuluj zamówienie",
        "order_cancelled_client": "Zamówienie anulowane. Jeśli zmienisz zdanie — wróć do sklepu 🛒",
        "order_cancelled_admin_note": "❌ Klient anulował zamówienie.",
        "cancel_confirm_title": "Anulować zamówienie?",
        "cancel_confirm_message": "Zamówienie {order_no} zostanie anulowane.",
        "cancel_confirm_yes": "Tak, anuluj",
        "cancel_confirm_no": "Nie, zostaw",
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
            "❗️Po opłaceniu prześlij tutaj koniecznie <b>zrzut ekranu lub potwierdzenie PDF</b> "
            "przelewu — bez tego nie będziemy mogli potwierdzić zamówienia."
        ),
        "invalid_proof_format": (
            "To nie wygląda na zrzut ekranu ani potwierdzenie 🤔\n"
            "Wyślij, proszę, zdjęcie ekranu płatności lub plik PDF."
        ),
        "proof_required_reminder": (
            "Aby potwierdzić zamówienie, wyślij tutaj <b>zrzut ekranu płatności</b> "
            "lub <b>potwierdzenie PDF</b> 📸📄"
        ),
        "order_autocancelled_client": (
            "⏰ Zamówienie {order_no} zostało anulowane automatycznie — minęło 30 min "
            "bez potwierdzenia płatności.\n\n"
            "Jeśli jednak zapłaciłeś(-aś) — po prostu złóż zamówienie ponownie "
            "i od razu wyślij zrzut ekranu lub potwierdzenie 🙏"
        ),
        "quick_reply_delay": "🚚 Przepraszamy za opóźnienie! Zamówienie {order_no} jest nieznacznie opóźnione, już nad tym pracujemy i wkrótce zostanie wysłane.",
        "quick_reply_addr": "📍 Proszę potwierdzić dokładny adres lub numer paczkomatu InPost dla zamówienia {order_no} — abyśmy mogli wysłać przesyłkę bez opóźnień.",
        "quick_reply_thanks": "🙏 Dziękujemy za zamówienie {order_no}! Cieszymy się, że wybrałeś/aś HOLLY LIQUID 🖤",
        "quick_reply_sent_admin": "✅ Szablon wysłany do klienta.",
        "payment_button": "✅ Płatność wysłana",
        "payment_ack_callback": "Dziękujemy! Zamówienie przekazano administratorowi.",
        "final_photo": (
            "✅ Dziękujemy! Zrzut ekranu i zamówienie przekazano administratorowi.\n"
            "Skontaktujemy się wkrótce w celu potwierdzenia.\n\n"
            "❓ Masz pytania lub problemy? Napisz do menedżera @hollymollydeal\n\n"
            "🎉 Dziękujemy za zamówienie!\n"
            "Holly Liquid — twój najlepszy wybór"
        ),
        "final_button": (
            "✅ Dziękujemy! Zamówienie przekazano administratorowi.\n"
            "Skontaktujemy się wkrótce w celu potwierdzenia płatności i dostawy.\n\n"
            "❓ Masz pytania lub problemy? Napisz do menedżera @hollymollydeal\n\n"
            "🎉 Dziękujemy za zamówienie!\n"
            "Holly Liquid — twój najlepszy wybór"
        ),
        "fallback": (
            "Przyjmuję zamówienia przez sklep 🛒\n\n"
            "Kliknij przycisk <b>«🛒 Otwórz sklep»</b> na dole ekranu, "
            "aby wybrać produkty.\n\n"
            "Jeśli nie widzisz przycisku — napisz /start\n"
            "Instrukcja ponownie — /help\n\n"
            "Pytania do menedżera: @hollymollydeal"
        ),
        "invalid_data": "Nie udało się odczytać zamówienia. Spróbuj ponownie przez sklep.",
        "order_no_label": "Numer zamówienia",
        "payment_confirmed": (
            "✅ <b>Płatność zaksięgowana!</b>\n\n"
            "Zamówienie <b>{order_no}</b> przyjęte do realizacji.\n"
            "Pakujemy je i wkrótce przekażemy do InPost.\n\n"
            "Dziękujemy za zamówienie! 🖤"
        ),
        "tracking_sent": (
            "📦 <b>Zamówienie wysłane!</b>\n\n"
            "Zamówienie: <b>{order_no}</b>\n"
            "Numer przesyłki InPost: <code>{tracking}</code>\n\n"
            "Śledzenie: https://inpost.pl/sledzenie-przesylek\n\n"
            "Dziękujemy za wybór HOLLY LIQUID! 🖤"
        ),
    },
    "en": {
        "welcome": (
            "💥 <b>HOLLY LIQUID</b> 💥\n"
            "<i>Your best choice</i>\n\n"

            "This is the official shop bot — browse the full range and place "
            "an order with InPost delivery anywhere in Poland.\n\n"

            "<b>How it works:</b>\n\n"

            "1️⃣ Tap <b>«🛒 Open shop»</b> below — the catalogue opens "
            "right here inside Telegram\n\n"

            "2️⃣ Pick your flavours and add them to the cart 🛒\n\n"

            "3️⃣ Tap <b>«Checkout»</b> → <b>«📦 InPost»</b> and enter your "
            "name, phone and locker number\n\n"

            "4️⃣ I'll send you the total and <b>BLIK</b> payment details right away\n\n"

            "5️⃣ After paying, send a screenshot here — and your order is on its way 📦\n\n"

            "───────────────\n"
            "🚚 <b>Delivery:</b> InPost Locker — 15 zł · Courier — 25 zł\n"
            "💳 <b>Payment:</b> BLIK, USDT or cash on meetup\n"
            "🕐 <b>Open:</b> Mon-Fri 6:00-23:00 · Sat-Sun 10:00-22:00\n"
            "───────────────\n\n"

            "❓ If you have any questions or run into any issues with "
            "your order, message our manager @hollymollydeal — "
            "he's always happy to help 🤝\n\n"

            "<b>Tap the button below to start</b> 👇"
        ),
        "open_shop_button": "🛒 Open shop",
        "order_ack": "🧾 Order received! Preparing payment details...",
        "cancel_order_button": "❌ Cancel order",
        "order_cancelled_client": "Order cancelled. If you change your mind — come back to the shop 🛒",
        "order_cancelled_admin_note": "❌ Client cancelled the order.",
        "cancel_confirm_title": "Cancel the order?",
        "cancel_confirm_message": "Order {order_no} will be cancelled.",
        "cancel_confirm_yes": "Yes, cancel",
        "cancel_confirm_no": "No, keep it",
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
            "❗️After paying, please send here a <b>payment screenshot or PDF receipt</b> "
            "— we can't confirm the order without it."
        ),
        "invalid_proof_format": (
            "That doesn't look like a screenshot or a receipt 🤔\n"
            "Please send a screenshot of the payment or a PDF file."
        ),
        "proof_required_reminder": (
            "To confirm your order, please send a <b>payment screenshot</b> "
            "or <b>PDF receipt</b> here 📸📄"
        ),
        "order_autocancelled_client": (
            "⏰ Order {order_no} was cancelled automatically — 30 minutes passed "
            "without payment confirmation.\n\n"
            "If you did pay — just place the order again and send the "
            "screenshot or receipt right away 🙏"
        ),
        "quick_reply_delay": "🚚 Sorry for the delay! Your order {order_no} is running a bit behind, we're already on it and it will ship soon.",
        "quick_reply_addr": "📍 Could you please confirm the exact address or InPost locker number for order {order_no} — so we can ship it without delays.",
        "quick_reply_thanks": "🙏 Thank you for order {order_no}! Glad you chose HOLLY LIQUID 🖤",
        "quick_reply_sent_admin": "✅ Template sent to the client.",
        "payment_button": "✅ Payment sent",
        "payment_ack_callback": "Thank you! Order sent to the admin.",
        "final_photo": (
            "✅ Thank you! Payment screenshot and order sent to the admin.\n"
            "We'll contact you shortly to confirm.\n\n"
            "❓ Questions or problems? Message the manager @hollymollydeal\n\n"
            "🎉 Thank you for your order!\n"
            "Holly Liquid — your best choice"
        ),
        "final_button": (
            "✅ Thank you! Order sent to the admin.\n"
            "We'll contact you shortly to confirm payment and delivery.\n\n"
            "❓ Questions or problems? Message the manager @hollymollydeal\n\n"
            "🎉 Thank you for your order!\n"
            "Holly Liquid — your best choice"
        ),
        "fallback": (
            "I take orders through the shop 🛒\n\n"
            "Tap the <b>«🛒 Open shop»</b> button at the bottom "
            "to pick your products.\n\n"
            "If you don't see the button — type /start\n"
            "Show instructions again — /help\n\n"
            "Questions to the manager: @hollymollydeal"
        ),
        "invalid_data": "Couldn't read the order. Please try again through the shop.",
        "order_no_label": "Order number",
        "payment_confirmed": (
            "✅ <b>Payment received!</b>\n\n"
            "Order <b>{order_no}</b> is confirmed.\n"
            "We're packing it and will hand it to InPost shortly.\n\n"
            "Thank you for your order! 🖤"
        ),
        "tracking_sent": (
            "📦 <b>Order shipped!</b>\n\n"
            "Order: <b>{order_no}</b>\n"
            "InPost tracking number: <code>{tracking}</code>\n\n"
            "Track it: https://inpost.pl/sledzenie-przesylek\n\n"
            "Thank you for choosing HOLLY LIQUID! 🖤"
        ),
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


class AdminForm(StatesGroup):
    """Стан менеджера, коли він вводить номер посилки для клієнта."""
    waiting_tracking = State()


def generate_order_no() -> str:
    """Короткий читабельний номер замовлення, напр. HL-1908-4821."""
    return f"HL-{datetime.now().strftime('%d%m')}-{random.randint(1000, 9999)}"


# ---------------------------------------------------------------------------
# KEYBOARDS
# ---------------------------------------------------------------------------

def open_shop_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "open_shop_button"), web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
    )


def admin_order_keyboard(client_id: int, order_no: str, client_username: str = None) -> InlineKeyboardMarkup:
    """Кнопки під замовленням у чаті менеджера."""
    rows = [
        [InlineKeyboardButton(
            text="✅ Оплату зараховано",
            callback_data=f"adm_pay:{client_id}:{order_no}",
        )],
        [InlineKeyboardButton(
            text="📦 Надіслати номер посилки",
            callback_data=f"adm_trk:{client_id}:{order_no}",
        )],
    ]
    if client_username:
        # Пряме посилання на чат з клієнтом — працює, лише якщо в нього є
        # публічний username. Якщо ні, кнопки не буде (Telegram не дозволяє
        # відкрити приватний чат за самим лише user_id).
        rows.append([InlineKeyboardButton(
            text="💬 Написати клієнту",
            url=f"https://t.me/{client_username}",
        )])
    # Швидкі шаблонні відповіді клієнту — надсилаються від імені бота
    # одним кліком, без потреби набирати текст вручну.
    rows.append([
        InlineKeyboardButton(text="🚚 Затримка", callback_data=f"qr_delay:{client_id}:{order_no}"),
        InlineKeyboardButton(text="📍 Адреса", callback_data=f"qr_addr:{client_id}:{order_no}"),
        InlineKeyboardButton(text="🙏 Дякуємо", callback_data=f"qr_thanks:{client_id}:{order_no}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_payment_keyboard(lang: str) -> InlineKeyboardMarkup:
    # Кнопки підтвердження оплати без доказу немає навмисно — клієнт
    # обов'язково має надіслати скрін або PDF квитанції.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "cancel_order_button"), callback_data="cancel_order")],
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


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext):
    """Повторно показує інструкцію — на випадок, якщо клієнт загубив її."""
    data = await state.get_data()
    lang = data.get("lang")
    if not lang:
        lang = (message.from_user.language_code or "ua")[:2]
        if lang not in TEXTS:
            lang = "ua"

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

    # Швидке підтвердження, щоб клієнт одразу бачив, що замовлення дійшло,
    # поки формуються реквізити (це майже миттєво, але для клієнта відчутно).
    try:
        await message.answer(t(lang, "order_ack"))
    except Exception as e:
        logger.warning(f"Не вдалося надіслати order_ack: {e}")

    order_no = generate_order_no()

    await state.update_data(
        lang=lang,
        items=items,
        total=total,
        name=name,
        phone=phone,
        point=point,
        order_no=order_no,
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
    order_text = f"🧾 {t(lang, 'order_no_label')}: <b>{order_no}</b>\n\n" + order_text

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
            reply_markup=admin_order_keyboard(message.from_user.id, order_no, message.from_user.username),
        )
    except Exception as e:
        logger.error(f"Failed to notify admin about new order: {e}")

    # Якщо за PAYMENT_REMINDER_MINUTES менеджер так і не підтвердив оплату —
    # нагадуємо окремим повідомленням, щоб замовлення не загубилось.
    asyncio.create_task(
        remind_admin_if_unpaid(order_no, name, phone, message.from_user.username)
    )
    # А якщо за PAYMENT_AUTOCANCEL_MINUTES доказу оплати так і не буде —
    # замовлення скасовується автоматично.
    asyncio.create_task(
        autocancel_unpaid_order(order_no, message.from_user.id, name, phone, message.from_user.username)
    )


@router.callback_query(F.data == "cancel_order")
async def cancel_order_confirm(callback: CallbackQuery, state: FSMContext):
    """Клієнт натиснув «Скасувати замовлення» — питаємо підтвердження."""
    data = await state.get_data()
    lang = data.get("lang", "ua")
    order_no = data.get("order_no", "—")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=t(lang, "cancel_confirm_yes"), callback_data="cancel_order_yes"),
            InlineKeyboardButton(text=t(lang, "cancel_confirm_no"), callback_data="cancel_order_no"),
        ]]
    )
    await callback.answer()
    await callback.message.answer(
        f"⚠️ <b>{t(lang, 'cancel_confirm_title')}</b>\n"
        f"{t(lang, 'cancel_confirm_message', order_no=order_no)}",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(F.data == "cancel_order_no")
async def cancel_order_dismiss(callback: CallbackQuery):
    """Клієнт передумав скасовувати."""
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "cancel_order_yes")
async def cancel_order_execute(callback: CallbackQuery, state: FSMContext):
    """Клієнт підтвердив скасування — повідомляємо і клієнта, і менеджера."""
    data = await state.get_data()
    lang = data.get("lang", "ua")
    order_no = data.get("order_no", "—")
    _resolved_orders.add(order_no)  # скасовано — нагадування більше не потрібне

    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        t(lang, "order_cancelled_client"),
        reply_markup=open_shop_keyboard(lang),
    )

    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"{t(lang, 'order_cancelled_admin_note')}\n"
                f"Замовлення: <b>{order_no}</b>\n"
                f"Клієнт: @{callback.from_user.username or callback.from_user.id}"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Не вдалося повідомити адміна про скасування: {e}")

    await state.clear()


@router.message(OrderForm.waiting_payment_proof, F.photo)
async def payment_proof_photo(message: Message, state: FSMContext):
    """Клієнт надіслав скрін оплати (фото)."""
    data = await state.get_data()
    lang = data.get("lang", "ua")
    order_no = data.get("order_no", generate_order_no())
    _resolved_orders.add(order_no)  # доказ отримано — нагадування більше не потрібне

    caption = build_admin_order_text(data, message.from_user, note="📸 Клієнт надіслав скрін оплати.")
    try:
        await bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=message.photo[-1].file_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=admin_order_keyboard(message.from_user.id, order_no, message.from_user.username),
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

    await message.answer(t(lang, "final_photo"), reply_markup=open_shop_keyboard(lang))
    await state.clear()


@router.message(OrderForm.waiting_payment_proof, F.document)
async def payment_proof_document(message: Message, state: FSMContext):
    """Клієнт надіслав PDF (або інший файл) квитанції замість скріна."""
    data = await state.get_data()
    lang = data.get("lang", "ua")
    order_no = data.get("order_no", generate_order_no())
    _resolved_orders.add(order_no)

    file_name = (message.document.file_name or "").lower()
    if not file_name.endswith((".pdf", ".jpg", ".jpeg", ".png", ".heic")):
        # Хтось випадково надіслав щось зовсім не те (напр. .docx, .txt).
        await message.answer(t(lang, "invalid_proof_format"))
        return

    caption = build_admin_order_text(data, message.from_user, note="📄 Клієнт надіслав PDF/файл квитанції.")
    try:
        await bot.send_document(
            chat_id=ADMIN_CHAT_ID,
            document=message.document.file_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=admin_order_keyboard(message.from_user.id, order_no, message.from_user.username),
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

    await message.answer(t(lang, "final_photo"), reply_markup=open_shop_keyboard(lang))
    await state.clear()


@router.message(OrderForm.waiting_payment_proof)
async def payment_proof_missing(message: Message, state: FSMContext):
    """
    Клієнт у стані очікування доказу оплати надіслав щось інше (текст,
    стікер тощо) — нагадуємо, що саме потрібно надіслати.
    """
    data = await state.get_data()
    lang = data.get("lang", "ua")
    await message.answer(t(lang, "proof_required_reminder"))


async def finalize_order(message: Message, state: FSMContext, lang: str, proof_note: str = "", client_id: int = None, client_username: str = None):
    data = await state.get_data()
    text = build_admin_order_text(data, message.chat, proof_note)
    order_no = data.get("order_no", "—")
    _resolved_orders.add(order_no)  # клієнт вже щось відповів — нагадування більше не потрібне
    # Для callback-кнопки message.chat — це чат клієнта, тож беремо його id,
    # якщо явно не передали інший.
    target_client_id = client_id or message.chat.id
    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=text,
            parse_mode="HTML",
            reply_markup=admin_order_keyboard(target_client_id, order_no, client_username),
        )
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

    order_no = data.get("order_no", "—")

    # Візуальний статус замовлення — за текстом примітки видно, на якому
    # етапі перебуває замовлення, без потреби вчитуватись у деталі.
    if "скрін" in note.lower() or "надіслав" in note.lower():
        status_header = "📸 <b>Скрін оплати надіслано</b>"
    elif "кнопкою" in note.lower() or "підтвердив" in note.lower():
        status_header = "✅ <b>Клієнт підтвердив оплату</b>"
    elif "скасував" in note.lower():
        status_header = "❌ <b>Замовлення скасовано</b>"
    elif "очікує" in note.lower():
        status_header = "🕐 <b>Нове замовлення — очікує оплати</b>"
    else:
        status_header = "🔔 <b>Замовлення HOLLY LIQUID</b>"

    return (
        f"{status_header}\n\n"
        f"Номер: <b>{order_no}</b>\n"
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


# ---------------------------------------------------------------------------
# ДІЇ МЕНЕДЖЕРА: підтвердження оплати та надсилання номера посилки
# ---------------------------------------------------------------------------

async def remind_admin_if_unpaid(order_no: str, name: str, phone: str, username: str = None):
    """Через PAYMENT_REMINDER_MINUTES нагадує менеджеру, якщо оплата ще не підтверджена."""
    await asyncio.sleep(PAYMENT_REMINDER_MINUTES * 60)

    if order_no in _resolved_orders:
        return  # вже підтверджено або скасовано — нагадування не потрібне

    contact = f"@{username}" if username else phone
    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"⏰ <b>Нагадування</b>\n\n"
                f"Замовлення <b>{order_no}</b> від {name} ({contact}) "
                f"досі не підтверджено — минуло {PAYMENT_REMINDER_MINUTES} хв.\n"
                f"Перевірте, чи оплата вже надійшла."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Не вдалося надіслати нагадування про замовлення {order_no}: {e}")


async def autocancel_unpaid_order(order_no: str, client_id: int, name: str, phone: str, username: str = None):
    """
    Через PAYMENT_AUTOCANCEL_MINUTES автоматично скасовує замовлення,
    якщо клієнт так і не надіслав доказ оплати. Звільняє менеджера від
    потреби вручну відстежувати "завислі" замовлення.
    """
    await asyncio.sleep(PAYMENT_AUTOCANCEL_MINUTES * 60)

    if order_no in _resolved_orders:
        return  # клієнт уже щось відповів, або менеджер підтвердив/скасував

    _resolved_orders.add(order_no)

    # Очищуємо стан клієнта, щоб він не "застряг" у режимі очікування
    # доказу оплати, якщо вирішить повернутись пізніше.
    try:
        key = StorageKey(bot_id=bot.id, chat_id=client_id, user_id=client_id)
        await dp.storage.set_state(key, None)
        await dp.storage.set_data(key, {})
    except Exception as e:
        logger.warning(f"Не вдалося очистити стан клієнта {client_id}: {e}")

    lang = await get_client_lang(client_id)
    try:
        await bot.send_message(
            chat_id=client_id,
            text=t(lang, "order_autocancelled_client", order_no=order_no),
            reply_markup=open_shop_keyboard(lang),
        )
    except Exception as e:
        logger.warning(f"Не вдалося повідомити клієнта {client_id} про автоскасування: {e}")

    contact = f"@{username}" if username else phone
    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"🕐 <b>Замовлення скасовано автоматично</b>\n\n"
                f"Замовлення <b>{order_no}</b> від {name} ({contact}) "
                f"скасовано — минуло {PAYMENT_AUTOCANCEL_MINUTES} хв без доказу оплати."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Не вдалося повідомити адміна про автоскасування {order_no}: {e}")


async def get_client_lang(client_id: int) -> str:
    """
    Мова клієнта для відповіді. Стан клієнта може бути вже очищений,
    тому за замовчуванням українська.
    """
    try:
        key = StorageKey(bot_id=bot.id, chat_id=client_id, user_id=client_id)
        data = await dp.storage.get_data(key)
        lang = data.get("lang", "ua")
        return lang if lang in TEXTS else "ua"
    except Exception:
        return "ua"


@router.callback_query(F.data.startswith("qr_"))
async def admin_quick_reply(callback: CallbackQuery):
    """
    Менеджер натиснув одну з кнопок швидкої відповіді (🚚 Затримка,
    📍 Адреса, 🙏 Дякуємо) — надсилаємо клієнту готовий шаблон його мовою.
    """
    try:
        action, client_id_raw, order_no = callback.data.split(":", 2)
        client_id = int(client_id_raw)
    except (ValueError, AttributeError):
        await callback.answer("Не вдалося прочитати дані замовлення", show_alert=True)
        return

    template_key = {
        "qr_delay": "quick_reply_delay",
        "qr_addr": "quick_reply_addr",
        "qr_thanks": "quick_reply_thanks",
    }.get(action)

    if not template_key:
        await callback.answer("Невідомий шаблон", show_alert=True)
        return

    lang = await get_client_lang(client_id)
    try:
        await bot.send_message(
            chat_id=client_id,
            text=t(lang, template_key, order_no=order_no),
        )
        await callback.answer(t(lang, "quick_reply_sent_admin"))
    except Exception as e:
        logger.error(f"Не вдалося надіслати шаблон клієнту {client_id}: {e}")
        await callback.answer(
            "Не вдалося надіслати повідомлення клієнту. "
            "Можливо, він заблокував бота.",
            show_alert=True,
        )


@router.callback_query(F.data.startswith("adm_pay:"))
async def admin_confirm_payment(callback: CallbackQuery):
    """Менеджер натиснув «Оплату зараховано» — повідомляємо клієнта."""
    try:
        _, client_id_raw, order_no = callback.data.split(":", 2)
        client_id = int(client_id_raw)
    except (ValueError, AttributeError):
        await callback.answer("Не вдалося прочитати дані замовлення", show_alert=True)
        return

    _resolved_orders.add(order_no)  # менеджер підтвердив — нагадування більше не потрібне
    lang = await get_client_lang(client_id)
    try:
        await bot.send_message(
            chat_id=client_id,
            text=t(lang, "payment_confirmed", order_no=order_no),
            parse_mode="HTML",
        )
        await callback.answer("✅ Клієнта повідомлено про зарахування оплати")
        # Позначаємо в чаті менеджера, що дію вже виконано
        await callback.message.reply(
            f"✅ Оплату по замовленню <b>{order_no}</b> підтверджено, клієнта повідомлено.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Не вдалося повідомити клієнта {client_id}: {e}")
        await callback.answer(
            "Не вдалося надіслати повідомлення клієнту. "
            "Можливо, він заблокував бота.",
            show_alert=True,
        )


@router.callback_query(F.data.startswith("adm_trk:"))
async def admin_ask_tracking(callback: CallbackQuery, state: FSMContext):
    """Менеджер натиснув «Надіслати номер посилки» — просимо ввести номер."""
    try:
        _, client_id_raw, order_no = callback.data.split(":", 2)
        client_id = int(client_id_raw)
    except (ValueError, AttributeError):
        await callback.answer("Не вдалося прочитати дані замовлення", show_alert=True)
        return

    await state.set_state(AdminForm.waiting_tracking)
    await state.update_data(track_client_id=client_id, track_order_no=order_no)
    await callback.answer()
    await callback.message.reply(
        f"📦 Надішліть номер посилки InPost для замовлення <b>{order_no}</b>\n"
        f"(або напишіть <code>скасувати</code>, щоб відмінити)",
        parse_mode="HTML",
    )


@router.message(AdminForm.waiting_tracking)
async def admin_send_tracking(message: Message, state: FSMContext):
    """Менеджер ввів номер посилки — пересилаємо його клієнту."""
    tracking = (message.text or "").strip()

    if tracking.lower() in ("скасувати", "cancel", "/cancel"):
        await state.clear()
        await message.answer("Скасовано.")
        return

    if not tracking:
        await message.answer("Порожнє повідомлення. Надішліть номер посилки текстом.")
        return

    data = await state.get_data()
    client_id = data.get("track_client_id")
    order_no = data.get("track_order_no", "—")
    await state.clear()

    if not client_id:
        await message.answer("Втрачено дані замовлення. Натисніть кнопку під замовленням ще раз.")
        return

    lang = await get_client_lang(client_id)
    try:
        await bot.send_message(
            chat_id=client_id,
            text=t(lang, "tracking_sent", order_no=order_no, tracking=tracking),
            parse_mode="HTML",
        )
        await message.answer(
            f"📦 Номер посилки <code>{tracking}</code> надіслано клієнту "
            f"(замовлення <b>{order_no}</b>).",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Не вдалося надіслати трек клієнту {client_id}: {e}")
        await message.answer(
            "Не вдалося надіслати повідомлення клієнту. Можливо, він заблокував бота."
        )


@router.message()
async def fallback(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        data = await state.get_data()
        lang = data.get("lang", "ua")
        await message.answer(t(lang, "fallback"), parse_mode="HTML")


# ---------------------------------------------------------------------------
# ENTRYPOINT
# ---------------------------------------------------------------------------

async def ensure_webhook(expected_url: str):
    """
    Перевіряє, що webhook справді зареєстрований, і відновлює його за потреби.

    Потрібно, бо під час оновлення на Render старий екземпляр може вимкнутись
    уже ПІСЛЯ того, як новий зареєстрував webhook, і зіпсувати налаштування.
    """
    try:
        info = await bot.get_webhook_info()
        if info.url != expected_url:
            logger.warning(
                f"Webhook збився (зараз: '{info.url or 'порожній'}'). Відновлюю..."
            )
            await bot.set_webhook(expected_url, drop_pending_updates=False)
            logger.info("Webhook відновлено")
    except Exception as e:
        logger.error(f"Не вдалося перевірити webhook: {e}")


async def webhook_watchdog(expected_url: str):
    """Раз на 10 хвилин переконується, що webhook на місці."""
    while True:
        await asyncio.sleep(600)
        await ensure_webhook(expected_url)


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

    # Через 20 секунд перевіряємо ще раз — на випадок, якщо старий екземпляр
    # вимкнувся вже після нас і встиг зіпсувати налаштування.
    async def recheck_later():
        await asyncio.sleep(20)
        await ensure_webhook(webhook_url)

    asyncio.create_task(recheck_later())
    asyncio.create_task(webhook_watchdog(webhook_url))


async def on_shutdown(app: web.Application):
    """
    НЕ видаляємо webhook при зупинці!

    Render під час оновлення на кілька секунд тримає два екземпляри одночасно:
    новий уже запустився і зареєстрував webhook, а старий саме вимикається.
    Якщо старий екземпляр викличе delete_webhook(), він зітре щойно створений
    webhook нового — і бот перестане отримувати повідомлення.

    Webhook має жити далі, його просто перезапише наступний запуск.
    """
    try:
        await bot.session.close()
    except Exception as e:
        logger.warning(f"Не вдалося акуратно закрити сесію: {e}")
    logger.info("Сервіс зупинено (webhook залишено активним)")


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
