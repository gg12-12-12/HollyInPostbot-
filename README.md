# HOLLY LIQUID — бот для замовлень (безкоштовний хостинг)

Бот працює в режимі **webhook** — Telegram сам надсилає йому повідомлення.
Завдяки цьому його можна безкоштовно тримати на Render.com.

---

## Що вам знадобиться

- Сайт (Mini App) вже викладений на GitHub Pages — адреса типу
  `https://ваш_логін.github.io/holyliquid/`
- Токен бота від @BotFather
- Ваш Telegram chat_id
- Номер телефону для BLIK

---

## КРОК 1. Дізнатись свій chat_id

1. У Telegram знайдіть бота **@userinfobot**
2. Натисніть Start
3. Він покаже ваш `Id` — це число і є `ADMIN_CHAT_ID`. Запишіть його.

---

## КРОК 2. Завантажити код на GitHub

1. Зайдіть на [github.com](https://github.com) → **New repository**
2. Назвіть, наприклад, `holyliquid-bot`, зробіть його **Public**, натисніть Create
3. На сторінці репозиторію натисніть **"uploading an existing file"**
4. Перетягніть три файли: `bot.py`, `requirements.txt`, `Procfile`
5. Натисніть **Commit changes**

---

## КРОК 3. Створити сервіс на Render

1. Зайдіть на [render.com](https://render.com), зареєструйтесь через GitHub
2. Натисніть **New +** → **Web Service**
   (саме **Web Service**, НЕ Background Worker — той платний)
3. Оберіть свій репозиторій `holyliquid-bot`
4. Заповніть поля:
   - **Name:** `holyliquid-bot` (або будь-яка назва)
   - **Region:** Frankfurt (найближче до Польщі)
   - **Branch:** `main`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Instance Type:** **Free**
5. Поки що **НЕ** натискайте Create — спершу додайте змінні (Крок 4)

---

## КРОК 4. Додати змінні середовища

На тій самій сторінці прокрутіть до розділу **Environment Variables**
і натисніть **Add Environment Variable**. Додайте чотири штуки:

| Назва (Key) | Значення (Value) |
|---|---|
| `BOT_TOKEN` | токен від @BotFather |
| `ADMIN_CHAT_ID` | ваш id з Кроку 1 |
| `BLIK_PHONE` | ваш номер для BLIK |
| `WEBAPP_URL` | `https://ваш_логін.github.io/holyliquid/` |

П'яту змінну (`BASE_WEBHOOK_URL`) додамо після створення — бо адресу
Render видає тільки після запуску.

Тепер натисніть **Create Web Service** і зачекайте 2-3 хвилини.

---

## КРОК 5. Додати адресу бота

1. Після запуску вгорі сторінки сервісу з'явиться адреса виду
   `https://holyliquid-bot.onrender.com` — **скопіюйте її**
2. Ліворуч оберіть **Environment** → **Add Environment Variable**
3. Додайте:
   - **Key:** `BASE_WEBHOOK_URL`
   - **Value:** ту адресу, що скопіювали
4. Натисніть **Save changes** — сервіс перезапуститься сам

---

## КРОК 6. Прив'язати Mini App до бота

1. У Telegram відкрийте **@BotFather**
2. `/mybots` → оберіть свого бота
3. **Bot Settings** → **Menu Button** → **Configure Menu Button**
4. Вставте адресу сайту: `https://ваш_логін.github.io/holyliquid/`
5. Назва кнопки: наприклад `Магазин`

---

## КРОК 7. Перевірити

1. Відкрийте свого бота в Telegram
2. Напишіть `/start`
3. Має з'явитись кнопка **"🛒 Відкрити магазин"**
4. Натисніть → відкриється сайт всередині Telegram
5. Додайте товар → Оформити → InPost → заповніть дані → Надіслати
6. Бот покаже реквізити BLIK, а **вам у Telegram прийде замовлення**

---

## ВАЖЛИВО: щоб бот не «засинав»

Безкоштовний Render присипляє сервіс після 15 хвилин без запитів.
Тоді перше замовлення після паузи прийде із затримкою ~30-50 секунд.

**Як прибрати затримку (безкоштовно):**

1. Зареєструйтесь на [uptimerobot.com](https://uptimerobot.com) (безкоштовно)
2. **Add New Monitor**
3. Заповніть:
   - **Monitor Type:** HTTP(s)
   - **Friendly Name:** HOLLY LIQUID bot
   - **URL:** ваша адреса з Кроку 5 (напр. `https://holyliquid-bot.onrender.com`)
   - **Monitoring Interval:** 5 minutes
4. **Create Monitor**

Тепер UptimeRobot стукатиме до бота кожні 5 хвилин, і той не засинатиме.

---

## Якщо щось не працює

**Бот не відповідає на /start**
→ На Render відкрийте вкладку **Logs**. Якщо там написано
`BASE_WEBHOOK_URL не задано!` — поверніться до Кроку 5.

**Кнопка «Відкрити магазин» відкриває порожню сторінку**
→ Перевірте `WEBAPP_URL` — адреса має відкриватись у звичайному браузері
і починатись з `https://`

**Замовлення не приходять вам**
→ Перевірте `ADMIN_CHAT_ID` (має бути число без пробілів).
Також переконайтесь, що ви хоча б раз написали своєму боту `/start` —
Telegram не дозволяє ботам писати першими.

**У логах помилка про порт**
→ Переконайтесь, що Start Command саме `python bot.py`, а не щось інше.
