"""
HOLLY LIQUID — формування PDF-звітів для менеджера.

Кирилиця у PDF потребує окремого шрифту (вбудовані шрифти PDF її не мають).
Тому шрифт шукається у кількох місцях, а якщо ніде не знайдено —
завантажується один раз і кешується.
"""

import io
import logging
import os
from datetime import datetime, timedelta, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

logger = logging.getLogger("holyliquid_export")

FONT_NAME = "HLSans"
FONT_NAME_BOLD = "HLSans-Bold"
_fonts_ready = False

# Де шукати шрифт із кирилицею
_FONT_CANDIDATES = [
    # 1. Поруч із ботом (якщо поклали файл у репозиторій)
    os.path.join(os.path.dirname(__file__), "DejaVuSans.ttf"),
    # 2. Типові системні шляхи
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    # 3. Кеш після завантаження
    "/tmp/DejaVuSans.ttf",
]
_FONT_BOLD_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/tmp/DejaVuSans-Bold.ttf",
]

_FONT_URL = "https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/DejaVuSans.ttf"
_FONT_BOLD_URL = "https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/DejaVuSans-Bold.ttf"


def _find_font(candidates: list[str]) -> str | None:
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _download_font(url: str, dest: str) -> str | None:
    """Завантажує шрифт один раз і кешує його у /tmp."""
    try:
        import urllib.request
        urllib.request.urlretrieve(url, dest)
        logger.info(f"Шрифт завантажено: {dest}")
        return dest
    except Exception as e:
        logger.error(f"Не вдалося завантажити шрифт: {e}")
        return None


def ensure_fonts() -> bool:
    """Реєструє шрифт із кирилицею. Повертає False, якщо нічого не вийшло."""
    global _fonts_ready
    if _fonts_ready:
        return True

    regular = _find_font(_FONT_CANDIDATES) or _download_font(_FONT_URL, "/tmp/DejaVuSans.ttf")
    if not regular:
        return False

    bold = _find_font(_FONT_BOLD_CANDIDATES) or _download_font(_FONT_BOLD_URL, "/tmp/DejaVuSans-Bold.ttf")

    try:
        pdfmetrics.registerFont(TTFont(FONT_NAME, regular))
        pdfmetrics.registerFont(TTFont(FONT_NAME_BOLD, bold or regular))
        _fonts_ready = True
        return True
    except Exception as e:
        logger.error(f"Не вдалося зареєструвати шрифт: {e}")
        return False


# ---------------------------------------------------------------------------

BRAND_YELLOW = colors.HexColor("#F5C518")
BRAND_INK = colors.HexColor("#171310")
BRAND_GREY = colors.HexColor("#F2F2F2")

STATUS_LABELS = {
    "pending": "Очікує оплати",
    "paid": "Оплачено",
    "shipped": "Відправлено",
    "cancelled": "Скасовано",
}


def _fmt_date(value: str) -> str:
    """2026-08-22T13:45:00+00:00 -> 22.08.2026"""
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except Exception:
        return value[:10]


def _items_summary(items) -> str:
    """Стислий опис товарів у замовленні."""
    if not items:
        return "—"
    if isinstance(items, str):
        return items
    parts = []
    for it in items:
        name = it.get("name", "—")
        qty = it.get("qty", 1)
        parts.append(f"{name} x{qty}")
    return ", ".join(parts)


def build_orders_pdf(orders: list, title: str = "Замовлення", period: str = "") -> bytes | None:
    """
    Формує PDF-таблицю із замовленнями.
    Повертає байти PDF або None, якщо шрифт недоступний.
    """
    if not ensure_fonts():
        return None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=title,
    )

    title_style = ParagraphStyle(
        "title", fontName=FONT_NAME_BOLD, fontSize=16, leading=20,
        textColor=BRAND_INK, spaceAfter=6,
    )
    sub_style = ParagraphStyle(
        "sub", fontName=FONT_NAME, fontSize=9, leading=12,
        textColor=colors.HexColor("#666666"), spaceAfter=10,
    )
    cell_style = ParagraphStyle(
        "cell", fontName=FONT_NAME, fontSize=7.5, leading=9,
    )
    head_style = ParagraphStyle(
        "head", fontName=FONT_NAME_BOLD, fontSize=8, leading=10,
        textColor=BRAND_INK,
    )

    story = [
        Paragraph("HOLLY LIQUID — " + title, title_style),
        Paragraph(
            (period + " · " if period else "")
            + f"Сформовано {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC"
            + f" · Записів: {len(orders)}",
            sub_style,
        ),
        Spacer(1, 4),
    ]

    headers = ["№ замовлення", "Дата", "Клієнт", "Телефон", "InPost", "Товари", "Сума", "Статус", "Трек-номер"]
    data = [[Paragraph(h, head_style) for h in headers]]

    total_sum = 0.0
    for o in orders:
        status = o.get("status", "")
        if status in ("paid", "shipped"):
            total_sum += float(o.get("total") or 0)

        data.append([
            Paragraph(str(o.get("order_no", "—")), cell_style),
            Paragraph(_fmt_date(o.get("created_at", "")), cell_style),
            Paragraph(str(o.get("customer_name") or "—"), cell_style),
            Paragraph(str(o.get("phone") or "—"), cell_style),
            Paragraph(str(o.get("inpost_point") or "—"), cell_style),
            Paragraph(_items_summary(o.get("items")), cell_style),
            Paragraph(f"{float(o.get('total') or 0):.0f} zł", cell_style),
            Paragraph(STATUS_LABELS.get(status, status or "—"), cell_style),
            Paragraph(str(o.get("tracking_no") or "—"), cell_style),
        ])

    col_widths = [26*mm, 18*mm, 32*mm, 28*mm, 20*mm, 68*mm, 16*mm, 24*mm, 28*mm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_YELLOW),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("BOX", (0, 0), (-1, -1), 1, BRAND_INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_GREY]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)

    story.append(Spacer(1, 8))
    total_style = ParagraphStyle("total", fontName=FONT_NAME_BOLD, fontSize=10, textColor=BRAND_INK)
    story.append(Paragraph(f"Разом (оплачені + відправлені): {total_sum:.2f} zł", total_style))

    try:
        doc.build(story)
    except Exception as e:
        logger.error(f"Не вдалося зібрати PDF: {e}")
        return None

    return buf.getvalue()


def build_clients_pdf(clients: list) -> bytes | None:
    """Формує PDF-таблицю з клієнтами."""
    if not ensure_fonts():
        return None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="Клієнти",
    )

    title_style = ParagraphStyle("title", fontName=FONT_NAME_BOLD, fontSize=16, leading=20,
                                 textColor=BRAND_INK, spaceAfter=6)
    sub_style = ParagraphStyle("sub", fontName=FONT_NAME, fontSize=9, leading=12,
                               textColor=colors.HexColor("#666666"), spaceAfter=10)
    cell_style = ParagraphStyle("cell", fontName=FONT_NAME, fontSize=8, leading=10)
    head_style = ParagraphStyle("head", fontName=FONT_NAME_BOLD, fontSize=9, textColor=BRAND_INK)

    story = [
        Paragraph("HOLLY LIQUID — Клієнти", title_style),
        Paragraph(
            f"Сформовано {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC"
            f" · Записів: {len(clients)}",
            sub_style,
        ),
        Spacer(1, 4),
    ]

    headers = ["Ім'я", "Username", "Мова", "Замовлень", "Витрачено", "З нами від"]
    data = [[Paragraph(h, head_style) for h in headers]]

    for cl in clients:
        uname = cl.get("username")
        data.append([
            Paragraph(str(cl.get("first_name") or "—"), cell_style),
            Paragraph(f"@{uname}" if uname else "—", cell_style),
            Paragraph(str(cl.get("lang") or "—").upper(), cell_style),
            Paragraph(str(cl.get("orders_count") or 0), cell_style),
            Paragraph(f"{float(cl.get('total_spent') or 0):.0f} zł", cell_style),
            Paragraph(_fmt_date(cl.get("first_seen", "")), cell_style),
        ])

    table = Table(data, colWidths=[40*mm, 38*mm, 16*mm, 24*mm, 26*mm, 28*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_YELLOW),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("BOX", (0, 0), (-1, -1), 1, BRAND_INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_GREY]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)

    try:
        doc.build(story)
    except Exception as e:
        logger.error(f"Не вдалося зібрати PDF клієнтів: {e}")
        return None

    return buf.getvalue()
