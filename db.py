"""
HOLLY LIQUID — робота з базою даних (Supabase).

Усі функції написані так, щоб НІКОЛИ не ламати бота:
якщо база недоступна, функція просто повертає порожній результат
і пише попередження в лог. Замовлення при цьому все одно дійде
до менеджера — просто не збережеться в історії.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("holyliquid_db")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_client = None


def get_client():
    """Ліниво створює клієнт Supabase при першому зверненні."""
    global _client
    if _client is not None:
        return _client
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.warning(
            "SUPABASE_URL / SUPABASE_KEY не задані — бот працює без бази даних."
        )
        return None
    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Підключення до Supabase встановлено")
        return _client
    except Exception as e:
        logger.error(f"Не вдалося підключитись до Supabase: {e}")
        return None


def is_enabled() -> bool:
    """Чи налаштована база даних."""
    return get_client() is not None


# ---------------------------------------------------------------------------
# КЛІЄНТИ
# ---------------------------------------------------------------------------

def upsert_client(chat_id: int, username: str = None, first_name: str = None, lang: str = "ua"):
    """Створює або оновлює запис клієнта. Викликається при кожному /start."""
    sb = get_client()
    if not sb:
        return
    try:
        now = datetime.now(timezone.utc).isoformat()
        sb.table("clients").upsert({
            "chat_id": chat_id,
            "username": username,
            "first_name": first_name,
            "lang": lang,
            "last_seen": now,
            "is_blocked": False,
        }, on_conflict="chat_id").execute()
    except Exception as e:
        logger.error(f"upsert_client({chat_id}) не вдалось: {e}")


def mark_client_blocked(chat_id: int):
    """Позначає, що клієнт заблокував бота — щоб не слати йому розсилки."""
    sb = get_client()
    if not sb:
        return
    try:
        sb.table("clients").update({"is_blocked": True}).eq("chat_id", chat_id).execute()
    except Exception as e:
        logger.error(f"mark_client_blocked({chat_id}) не вдалось: {e}")


def get_all_client_ids(only_active: bool = True) -> list[int]:
    """Список chat_id для розсилки."""
    sb = get_client()
    if not sb:
        return []
    try:
        q = sb.table("clients").select("chat_id")
        if only_active:
            q = q.eq("is_blocked", False)
        res = q.execute()
        return [row["chat_id"] for row in (res.data or [])]
    except Exception as e:
        logger.error(f"get_all_client_ids не вдалось: {e}")
        return []


# ---------------------------------------------------------------------------
# ЗАМОВЛЕННЯ
# ---------------------------------------------------------------------------

def create_order(order_no: str, chat_id: int, lang: str, customer_name: str,
                 phone: str, inpost_point: str, items: list, total: float,
                 promo_code: str = None):
    """Зберігає нове замовлення зі статусом pending."""
    sb = get_client()
    if not sb:
        return
    try:
        sb.table("orders").insert({
            "order_no": order_no,
            "chat_id": chat_id,
            "lang": lang,
            "customer_name": customer_name,
            "phone": phone,
            "inpost_point": inpost_point,
            "items": items,
            "total": total,
            "promo_code": promo_code,
            "status": "pending",
        }).execute()
    except Exception as e:
        logger.error(f"create_order({order_no}) не вдалось: {e}")


def set_order_status(order_no: str, status: str, tracking_no: str = None):
    """
    Оновлює статус замовлення.
    status: pending | paid | shipped | cancelled
    """
    sb = get_client()
    if not sb:
        return
    try:
        now = datetime.now(timezone.utc).isoformat()
        payload = {"status": status}
        if status == "paid":
            payload["paid_at"] = now
        elif status == "shipped":
            payload["shipped_at"] = now
            if tracking_no:
                payload["tracking_no"] = tracking_no
        elif status == "cancelled":
            payload["cancelled_at"] = now

        sb.table("orders").update(payload).eq("order_no", order_no).execute()

        # Коли оплата підтверджена — оновлюємо лічильники клієнта
        if status == "paid":
            _bump_client_stats(order_no)
    except Exception as e:
        logger.error(f"set_order_status({order_no}, {status}) не вдалось: {e}")


def _bump_client_stats(order_no: str):
    """Збільшує лічильник замовлень і суму витрат клієнта."""
    sb = get_client()
    if not sb:
        return
    try:
        res = sb.table("orders").select("chat_id,total").eq("order_no", order_no).limit(1).execute()
        if not res.data:
            return
        row = res.data[0]
        chat_id, total = row["chat_id"], float(row["total"] or 0)

        cur = sb.table("clients").select("orders_count,total_spent").eq("chat_id", chat_id).limit(1).execute()
        if not cur.data:
            return
        c = cur.data[0]
        sb.table("clients").update({
            "orders_count": (c.get("orders_count") or 0) + 1,
            "total_spent": float(c.get("total_spent") or 0) + total,
        }).eq("chat_id", chat_id).execute()
    except Exception as e:
        logger.error(f"_bump_client_stats({order_no}) не вдалось: {e}")


def get_client_orders(chat_id: int, limit: int = 10) -> list:
    """Історія замовлень клієнта — для особистого кабінету."""
    sb = get_client()
    if not sb:
        return []
    try:
        res = (sb.table("orders")
               .select("order_no,total,status,created_at,tracking_no")
               .eq("chat_id", chat_id)
               .order("created_at", desc=True)
               .limit(limit)
               .execute())
        return res.data or []
    except Exception as e:
        logger.error(f"get_client_orders({chat_id}) не вдалось: {e}")
        return []


def get_client_profile(chat_id: int) -> dict:
    """Дані клієнта для профілю: лічильники та збережена доставка."""
    sb = get_client()
    if not sb:
        return {}
    try:
        res = (sb.table("clients")
               .select("first_name,username,lang,orders_count,total_spent,first_seen,"
                       "saved_name,saved_phone,saved_point")
               .eq("chat_id", chat_id)
               .limit(1)
               .execute())
        return (res.data or [{}])[0]
    except Exception as e:
        logger.error(f"get_client_profile({chat_id}) не вдалось: {e}")
        return {}


def save_delivery_details(chat_id: int, name: str, phone: str, point: str):
    """
    Запам'ятовує дані доставки, щоб наступного разу підставити їх
    автоматично і клієнту не довелось вписувати все заново.
    """
    sb = get_client()
    if not sb:
        return
    try:
        sb.table("clients").update({
            "saved_name": name,
            "saved_phone": phone,
            "saved_point": point,
        }).eq("chat_id", chat_id).execute()
    except Exception as e:
        logger.error(f"save_delivery_details({chat_id}) не вдалось: {e}")


# ---------------------------------------------------------------------------
# СТАТИСТИКА
# ---------------------------------------------------------------------------

def get_stats() -> dict:
    """Зведена статистика для команди /stats."""
    sb = get_client()
    if not sb:
        return {}
    try:
        stats = {}

        clients = sb.table("clients").select("chat_id", count="exact").execute()
        stats["clients_total"] = clients.count or 0

        active = sb.table("clients").select("chat_id", count="exact").eq("is_blocked", False).execute()
        stats["clients_active"] = active.count or 0

        for status in ("pending", "paid", "shipped", "cancelled"):
            r = sb.table("orders").select("id", count="exact").eq("status", status).execute()
            stats[f"orders_{status}"] = r.count or 0

        paid = sb.table("orders").select("total").in_("status", ["paid", "shipped"]).execute()
        stats["revenue"] = sum(float(o["total"] or 0) for o in (paid.data or []))

        return stats
    except Exception as e:
        logger.error(f"get_stats не вдалось: {e}")
        return {}


# ---------------------------------------------------------------------------
# ЕКСПОРТ
# ---------------------------------------------------------------------------

def get_orders_for_export(days: int = None, status: str = None, limit: int = 500) -> list:
    """
    Вибірка замовлень для PDF-звіту.
      days   — за скільки останніх днів (None = за весь час)
      status — фільтр за статусом (None = усі)
    """
    sb = get_client()
    if not sb:
        return []
    try:
        q = sb.table("orders").select(
            "order_no,created_at,customer_name,phone,inpost_point,"
            "items,total,status,tracking_no"
        )
        if days:
            from datetime import timedelta
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            q = q.gte("created_at", since)
        if status:
            q = q.eq("status", status)
        res = q.order("created_at", desc=True).limit(limit).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"get_orders_for_export не вдалось: {e}")
        return []


def get_clients_for_export(limit: int = 1000) -> list:
    """Список клієнтів для PDF-звіту."""
    sb = get_client()
    if not sb:
        return []
    try:
        res = (sb.table("clients")
               .select("first_name,username,lang,orders_count,total_spent,first_seen")
               .order("total_spent", desc=True)
               .limit(limit)
               .execute())
        return res.data or []
    except Exception as e:
        logger.error(f"get_clients_for_export не вдалось: {e}")
        return []


# ---------------------------------------------------------------------------
# ПРОМОКОДИ
# ---------------------------------------------------------------------------

def get_active_promos() -> list:
    """Список активних промокодів."""
    sb = get_client()
    if not sb:
        return []
    try:
        res = sb.table("promo_codes").select("*").eq("is_active", True).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"get_active_promos не вдалось: {e}")
        return []


def add_promo(code: str, percent: int, max_uses: int = None) -> bool:
    """Додає новий промокод."""
    sb = get_client()
    if not sb:
        return False
    try:
        sb.table("promo_codes").upsert({
            "code": code.upper(),
            "percent": percent,
            "max_uses": max_uses,
            "is_active": True,
        }, on_conflict="code").execute()
        return True
    except Exception as e:
        logger.error(f"add_promo({code}) не вдалось: {e}")
        return False


def bump_promo_usage(code: str):
    """Збільшує лічильник використань промокоду (для лімітів)."""
    sb = get_client()
    if not sb:
        return
    try:
        cur = sb.table("promo_codes").select("used_count,max_uses").eq("code", code.upper()).limit(1).execute()
        if not cur.data:
            return
        row = cur.data[0]
        new_count = (row.get("used_count") or 0) + 1
        payload = {"used_count": new_count}
        # Досягли ліміту — автоматично вимикаємо код
        max_uses = row.get("max_uses")
        if max_uses and new_count >= max_uses:
            payload["is_active"] = False
        sb.table("promo_codes").update(payload).eq("code", code.upper()).execute()
    except Exception as e:
        logger.error(f"bump_promo_usage({code}) не вдалось: {e}")


def disable_promo(code: str) -> bool:
    """Вимикає промокод."""
    sb = get_client()
    if not sb:
        return False
    try:
        sb.table("promo_codes").update({"is_active": False}).eq("code", code.upper()).execute()
        return True
    except Exception as e:
        logger.error(f"disable_promo({code}) не вдалось: {e}")
        return False


# ---------------------------------------------------------------------------
# АСИНХРОННІ ОБГОРТКИ
#
# Клієнт Supabase працює синхронно. Якщо викликати його напряму з
# асинхронного обробника, він блокує весь бот — і Telegram не дочікується
# відповіді (особливо при першому виклику, коли завантажується бібліотека).
# Тому всі звернення до бази виконуються в окремому потоці.
# ---------------------------------------------------------------------------

async def warm_up():
    """Ініціалізує підключення заздалегідь, щоб перший клієнт не чекав."""
    await asyncio.to_thread(get_client)


async def a_is_enabled() -> bool:
    return await asyncio.to_thread(is_enabled)


async def a_upsert_client(*args, **kwargs):
    return await asyncio.to_thread(lambda: upsert_client(*args, **kwargs))


async def a_mark_client_blocked(*args, **kwargs):
    return await asyncio.to_thread(lambda: mark_client_blocked(*args, **kwargs))


async def a_get_all_client_ids(*args, **kwargs):
    return await asyncio.to_thread(lambda: get_all_client_ids(*args, **kwargs))


async def a_create_order(*args, **kwargs):
    return await asyncio.to_thread(lambda: create_order(*args, **kwargs))


async def a_set_order_status(*args, **kwargs):
    return await asyncio.to_thread(lambda: set_order_status(*args, **kwargs))


async def a_get_client_orders(*args, **kwargs):
    return await asyncio.to_thread(lambda: get_client_orders(*args, **kwargs))


async def a_get_client_profile(*args, **kwargs):
    return await asyncio.to_thread(lambda: get_client_profile(*args, **kwargs))


async def a_save_delivery_details(*args, **kwargs):
    return await asyncio.to_thread(lambda: save_delivery_details(*args, **kwargs))


async def a_get_stats(*args, **kwargs):
    return await asyncio.to_thread(lambda: get_stats(*args, **kwargs))


async def a_get_orders_for_export(*args, **kwargs):
    return await asyncio.to_thread(lambda: get_orders_for_export(*args, **kwargs))


async def a_get_clients_for_export(*args, **kwargs):
    return await asyncio.to_thread(lambda: get_clients_for_export(*args, **kwargs))


async def a_get_active_promos(*args, **kwargs):
    return await asyncio.to_thread(lambda: get_active_promos(*args, **kwargs))


async def a_add_promo(*args, **kwargs):
    return await asyncio.to_thread(lambda: add_promo(*args, **kwargs))


async def a_bump_promo_usage(*args, **kwargs):
    return await asyncio.to_thread(lambda: bump_promo_usage(*args, **kwargs))


async def a_disable_promo(*args, **kwargs):
    return await asyncio.to_thread(lambda: disable_promo(*args, **kwargs))
