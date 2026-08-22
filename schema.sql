-- ============================================================
-- HOLLY LIQUID — структура бази даних
-- Виконайте цей скрипт один раз у Supabase → SQL Editor
-- ============================================================

-- ------------------------------------------------------------
-- 1. КЛІЄНТИ
-- Кожен, хто хоч раз написав боту. Потрібно для розсилок.
-- ------------------------------------------------------------
create table if not exists clients (
    chat_id      bigint primary key,           -- Telegram ID клієнта
    username     text,                          -- @username (може бути порожнім)
    first_name   text,
    lang         text default 'ua',             -- ua / pl / en
    first_seen   timestamptz default now(),     -- коли вперше написав
    last_seen    timestamptz default now(),     -- останя активність
    is_blocked   boolean default false,         -- true, якщо заблокував бота
    orders_count integer default 0,             -- скільки разів замовляв
    total_spent  numeric(10,2) default 0        -- на яку суму загалом
);

-- ------------------------------------------------------------
-- 2. ЗАМОВЛЕННЯ
-- Історія всіх замовлень. Потрібно для статистики та кабінету.
-- ------------------------------------------------------------
create table if not exists orders (
    id           bigserial primary key,
    order_no     text unique not null,          -- напр. HL-1908-4821
    chat_id      bigint references clients(chat_id),
    lang         text default 'ua',

    -- Дані з форми
    customer_name text,
    phone         text,
    inpost_point  text,

    -- Товари зберігаємо як JSON — зручно, бо склад замовлення різний
    items         jsonb,
    total         numeric(10,2),

    -- Статус: pending → paid → shipped, або cancelled
    status        text default 'pending',
    promo_code    text,                          -- застосований промокод
    tracking_no   text,                          -- номер посилки InPost

    created_at    timestamptz default now(),
    paid_at       timestamptz,
    shipped_at    timestamptz,
    cancelled_at  timestamptz
);

-- Індекси для швидкого пошуку
create index if not exists idx_orders_chat_id on orders(chat_id);
create index if not exists idx_orders_status  on orders(status);
create index if not exists idx_orders_created on orders(created_at desc);

-- ------------------------------------------------------------
-- 3. ПРОМОКОДИ
-- Керуються командами бота, без редагування коду.
-- ------------------------------------------------------------
create table if not exists promo_codes (
    code         text primary key,              -- напр. NEWPLAYER10
    percent      integer not null,              -- знижка у відсотках
    is_active    boolean default true,
    max_uses     integer,                       -- ліміт використань (null = без ліміту)
    used_count   integer default 0,
    expires_at   timestamptz,                   -- термін дії (null = безстроково)
    created_at   timestamptz default now()
);

-- Початкові промокоди (ті, що вже є на сайті)
insert into promo_codes (code, percent) values
    ('NEWPLAYER10', 10),
    ('SATANA10', 10)
on conflict (code) do nothing;

-- ------------------------------------------------------------
-- ДОСТУП
-- Вимикаємо RLS, бо до бази звертається лише наш бот
-- зі службовим ключем (service_role), а не браузер клієнта.
-- ------------------------------------------------------------
alter table clients     disable row level security;
alter table orders      disable row level security;
alter table promo_codes disable row level security;
