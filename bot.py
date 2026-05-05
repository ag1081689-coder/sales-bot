import os
import json
import re
import anthropic
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

SHEET_ID = "1x5CfKVrgXZy1-1yVPoqAwcS0KpxeOyzxfA8shDt2qkw"
AV_SHEET_ID = "1f-1lkgr7nGiQofoREnhfbszjaJFu17OtZaMJ09_sLWw"
SECRET_PASSWORD = os.environ.get("SECRET_PASSWORD", "Adel2026")

PROJECTS = ["D11 BUSINESS", "D12 Medical", "METRO +", "TIJAN", "WW1", "WW2", "STAGE X", "RESALE", "MIDST"]

PROJECT_ALIASES = {
    "d11": "D11 BUSINESS",
    "d11 business": "D11 BUSINESS",
    "d12": "D12 Medical",
    "d12 medical": "D12 Medical",
    "ww1": "WW1",
    "waterway 1": "WW1",
    "ww2": "WW2",
    "waterway 2": "WW2",
    "tijan": "TIJAN",
    "midst": "MIDST",
    "stage x": "STAGE X",
    "stagex": "STAGE X",
    "resale": "RESALE",
    "metro": "METRO +",
    "metro +": "METRO +",
    "metro plus": "METRO +",
}

COMPANY_INFO = """
معمار دجلة للتطوير العقاري - MEMAAR DEGLA DEVELOPMENT
تأسست: 2019 في العاشر من رمضان
فريق: أكثر من 65 متخصص - تمويل ذاتي بالكامل
الموقع: memaardegla.com | 15409
المؤسسون: أ/ أحمد عبد العزيز | م/ معاذ باشا | أ/ محمد خليل
ملاحظة: جميع الوحدات إدارية أو تجارية أو طبية - لا توجد وحدات سكنية.
"""

creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
gc = gspread.service_account_from_dict(creds_json)
sh = gc.open_by_key(SHEET_ID)
av_sh = gc.open_by_key(AV_SHEET_ID)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

user_context = {}
chat_history = {}

def detect_project(text):
    text_lower = text.lower().strip()
    for alias, real in PROJECT_ALIASES.items():
        if alias in text_lower:
            return real
    for p in PROJECTS:
        if p.lower() in text_lower:
            return p
    return None

def extract_area(text):
    patterns = [r'(\d+)\s*متر', r'(\d+)\s*م²', r'(\d+)\s*م ', r'مساحت[هة]\s*(\d+)']
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None

def detect_unit_code(text):
    # يدور على كود زي D11 B01 أو WW1 C3
    pattern = r'\b([A-Za-z0-9]+\s+[A-Za-z0-9]+)\b'
    matches = re.findall(pattern, text.upper())
    for m in matches:
        parts = m.strip().split()
        if len(parts) == 2 and any(c.isdigit() for c in parts[1]):
            return m.strip()
    return None

def get_unit_from_sheet(unit_code, project_filter=None):
    try:
        for ws in av_sh.worksheets():
            if project_filter and project_filter.lower() not in ws.title.lower():
                continue
            data = ws.get_all_values()
            if not data:
                continue
            for row in data[1:]:
                if not row or not row[0].strip():
                    continue
                code_in_sheet = row[0].strip().upper().replace(" ", "")
                code_search = unit_code.strip().upper().replace(" ", "")
                if code_in_sheet == code_search:
                    # الأعمدة: A=code, C=area, D=price/m, E=discount, F=total, G=total after discount, H=down, I=batch, K=installments, L=delivery, M=status
                    return {
                        "sheet": ws.title,
                        "code": row[0] if len(row) > 0 else "",
                        "area": row[2] if len(row) > 2 else "",
                        "price_per_meter": row[3] if len(row) > 3 else "",
                        "discount": row[4] if len(row) > 4 else "",
                        "total_price": row[5] if len(row) > 5 else "",
                        "total_after_discount": row[6] if len(row) > 6 else "",
                        "downpayment": row[7] if len(row) > 7 else "",
                        "batch_after_year": row[8] if len(row) > 8 else "",
                        "installments": row[10] if len(row) > 10 else "",
                        "delivery_payment": row[11] if len(row) > 11 else "",
                        "status": row[12] if len(row) > 12 else ""
                    }
        return None
    except:
        return None

def get_project_status(project_filter=None):
    try:
        results = {}
        for ws in av_sh.worksheets():
            if project_filter and project_filter.lower() not in ws.title.lower():
                continue
            data = ws.get_all_values()
            counts = {"available": 0, "reserved": 0, "hold": 0}
            for row in data[1:]:
                if len(row) > 12:
                    s = row[12].strip().lower()
                    if s in counts:
                        counts[s] += 1
            if sum(counts.values()) > 0:
                results[ws.title] = counts
        return results
    except:
        return {}

def get_all_units(project_filter=None, status_filter=None, area_filter=None):
    try:
        all_units = []
        for ws in av_sh.worksheets():
            if project_filter and project_filter.lower() not in ws.title.lower():
                continue
            data = ws.get_all_values()
            for row in data[1:]:
                if not row or not row[0].strip() or len(row) < 13:
                    continue
                row_status = row[12].strip().lower()
                if not row_status:
                    continue
                if status_filter and row_status != status_filter.lower():
                    continue
                if area_filter:
                    try:
                        area_val = float(str(row[2]).replace(",", "").strip())
                        if abs(area_val - area_filter) > 2:
                            continue
                    except:
                        continue
                all_units.append({
                    "sheet": ws.title,
                    "code": row[0],
                    "area": row[2] if len(row) > 2 else "",
                    "total_after_discount": row[6] if len(row) > 6 else "",
                    "downpayment": row[7] if len(row) > 7 else "",
                    "status": row_status
                })
        return all_units
    except:
        return []

def format_status(results):
    if not results:
        return "لا توجد بيانات."
    text = ""
    for project, counts in results.items():
        total = sum(counts.values())
        text += f"📊 *{project}*\n"
        text += f"✅ متاح: {counts['available']}\n"
        text += f"🔴 محجوز: {counts['reserved']}\n"
        text += f"🔵 Hold: {counts['hold']}\n"
        text += f"📦 الإجمالي: {total}\n\n"
    return text if text else "لا توجد بيانات."

def format_units(units, title=""):
    if not units:
        return "لا توجد وحدات بهذه المواصفات."
    result = f"*{title}*\n\n" if title else ""
    current_sheet = ""
    for u in units[:30]:
        if u["sheet"] != current_sheet:
            current_sheet = u["sheet"]
            result += f"*{current_sheet}:*\n"
        status_emoji = "✅" if u["status"] == "available" else "🔴" if u["status"] == "reserved" else "🔵"
        result += f"• {u['code']} | {u['area']}م² | {u['total_after_discount']} جنيه | {status_emoji}\n"
    return result

def save_sale(project, unit, price, client_name):
    try:
        try:
            ws = sh.worksheet("المبيعات")
        except:
            ws = sh.add_worksheet(title="المبيعات", rows=1000, cols=10)
            ws.append_row(["المشروع", "الوحدة", "السعر", "اسم العميل", "التاريخ"])
        from datetime import datetime
        date = datetime.now().strftime("%Y-%m-%d %H:%M")
        ws.append_row([project, unit, price, client_name, date])
        return True
    except:
        return False

def get_sales_data():
    try:
        ws = sh.worksheet("المبيعات")
        data = ws.get_all_values()
        if len(data) <= 1:
            return "لا توجد مبيعات مسجلة حتى الآن."
        result = ""
        for row in data[1:]:
            if len(row) >= 4:
                result += f"• {row[0]} - {row[1]} - {row[2]} - {row[3]} - {row[4]}\n"
        return result
    except:
        return "لا توجد مبيعات مسجلة."

def get_project_info(project_name):
    try:
        ws = sh.worksheet(project_name)
        data = ws.get_all_values()
        result = ""
        for row in data[1:]:
            if len(row) >= 2 and row[0] and row[1]:
                result += f"{row[0]}: {row[1]}\n"
        return result
    except:
        return ""

def get_style_buttons():
    keyboard = [
        [
            InlineKeyboardButton("😣 Pain Point", callback_data="style_pain"),
            InlineKeyboardButton("📊 المقارنة", callback_data="style_compare")
        ],
        [
            InlineKeyboardButton("⏰ FOMO", callback_data="style_fomo"),
            InlineKeyboardButton("💰 ROI والأرقام", callback_data="style_roi")
        ],
        [
            InlineKeyboardButton("📖 القصة", callback_data="style_story"),
            InlineKeyboardButton("⭐ Social Proof", callback_data="style_social")
        ],
        [
            InlineKeyboardButton("💎 Exclusivity", callback_data="style_exclusive")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

STYLES = {
    "style_pain": ("Pain Point", "ابدأ بمشكلة العميل"),
    "style_compare": ("المقارنة", "قارن بين الإيجار والشراء"),
    "style_fomo": ("FOMO", "ضغط الوقت والندرة"),
    "style_roi": ("ROI والأرقام", "احسبله العائد"),
    "style_story": ("القصة", "قصة عميل نجح"),
    "style_social": ("Social Proof", "أرقام وشهادات"),
    "style_exclusive": ("Exclusivity", "الحصرية والندرة")
}

def add_to_history(user_id, role, content):
    if user_id not in chat_history:
        chat_history[user_id] = []
    chat_history[user_id].append({"role": role, "content": content})
    if len(chat_history[user_id]) > 20:
        chat_history[user_id] = chat_history[user_id][-20:]

def get_history(user_id):
    return chat_history.get(user_id, [])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_history[user_id] = []
    await update.message.reply_text(
        "مرحباً بك في معمار دجلة!\n\n"
        "يمكنني مساعدتك في:\n"
        "• تفاصيل وحدة بكودها (مثال: D11 B07)\n"
        "• الوحدات المتاحة والمحجوزة\n"
        "• إعلانات وسكريبتات احترافية\n"
        "• تسجيل المبيعات\n\n"
        "كيف يمكنني مساعدتك؟"
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    style_key = query.data
    if style_key not in STYLES:
        return
    style_name, style_instruction = STYLES[style_key]
    saved = user_context.get(user_id, {})
    project = saved.get("project", "")
    request = saved.get("request", "")
    project_info = get_project_info(project) if project else ""

    system = f"""أنت خبير تسويق عقاري في شركة معمار دجلة.
{COMPANY_INFO}
معلومات المشروع: {project_info}
تفاصيل العميل: {request}
الأسلوب: {style_name} - {style_instruction}
اكتب سكريبت واتساب بأسلوب مصري راقٍ.
لا تذكر أي اسم غير معمار دجلة."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=system,
        messages=[{"role": "user", "content": f"اكتب سكريبت {style_name} لمشروع {project}"}]
    )
    await query.edit_message_text(
        f"*سكريبت {style_name} - {project}*\n\n{response.content[0].text}",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()
    user_id = update.message.from_user.id
    msg_lower = user_message.lower()

    if user_context.get(user_id, {}).get("waiting_password"):
        if user_message == SECRET_PASSWORD:
            user_context[user_id]["waiting_password"] = False
            user_context[user_id]["authenticated"] = True
            sales = get_sales_data()
            await update.message.reply_text(f"سجل المبيعات:\n\n{sales}")
        else:
            await update.message.reply_text("كلمة المرور غير صحيحة.")
        return

    if "مبيعات" in msg_lower or "بايعين" in msg_lower or "احنا بعنا" in msg_lower:
        if user_context.get(user_id, {}).get("authenticated"):
            sales = get_sales_data()
            await update.message.reply_text(f"سجل المبيعات:\n\n{sales}")
        else:
            user_context[user_id] = {"waiting_password": True}
            await update.message.reply_text("من فضلك أدخل كلمة المرور:")
        return

    if "بيعة" in msg_lower or "بعنا" in msg_lower or "اتباع" in msg_lower:
        system = """استخرج معلومات البيعة وأرجع JSON فقط:
{"action":"sale","project":"اسم","unit":"وحدة","price":"سعر","client":"عميل"}"""
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )
        reply = response.content[0].text.strip()
        try:
            data = json.loads(reply[reply.find("{"):reply.rfind("}")+1])
            if data.get("action") == "sale":
                save_sale(data["project"], data["unit"], data["price"], data["client"])
                await update.message.reply_text(
                    f"✅ تم تسجيل البيعة\n"
                    f"المشروع: {data['project']} | الوحدة: {data['unit']}\n"
                    f"السعر: {data['price']} | العميل: {data['client']}"
                )
            return
        except:
            pass

    detected_project = detect_project(user_message)
    area_filter = extract_area(user_message)
    unit_code = detect_unit_code(user_message)

    # البحث عن وحدة بكودها
    if unit_code:
        unit = get_unit_from_sheet(unit_code, detected_project)
        if unit:
            status_emoji = "✅" if unit["status"] == "available" else "🔴" if unit["status"] == "reserved" else "🔵"
            text = f"*تفاصيل الوحدة {unit['code']}*\n\n"
            text += f"🏢 المشروع: {unit['sheet']}\n"
            text += f"📐 المساحة: {unit['area']}م²\n"
            text += f"💰 سعر المتر: {unit['price_per_meter']} جنيه\n"
            text += f"🏷️ الخصم: {unit['discount']} جنيه\n"
            text += f"💵 السعر الأصلي: {unit['total_price']}\n"
            text += f"✨ السعر بعد الخصم: {unit['total_after_discount']} جنيه\n"
            text += f"🔑 المقدم: {unit['downpayment']} جنيه\n"
            text += f"📅 القسط السنوي: {unit['batch_after_year']} جنيه\n"
            text += f"💳 قيمة الأقساط: {unit['installments']} جنيه\n"
            text += f"🏗️ دفعة التسليم: {unit['delivery_payment']} جنيه\n"
            text += f"📊 الحالة: {status_emoji} {unit['status']}"
            await update.message.reply_text(text, parse_mode="Markdown")
            return

    keywords_all = ["كل المشاريع", "كل حاجه", "الكل", "جميع", "overview"]
    keywords_status = ["كام وحدة", "وحدات", "متاح", "reserved", "hold", "الوضع", "احصائيه", "احصائية", "كام", "إتاحة", "اتاحة", "اتاحه"]
    keywords_available = ["متاح", "available", "فاضي", "المتاح"]

    if any(k in msg_lower for k in keywords_all) and not detected_project:
        results = get_project_status()
        text = format_status(results)
        await update.message.reply_text(f"📊 *ملخص جميع المشاريع*\n\n{text}", parse_mode="Markdown")
        return

    if any(k in msg_lower for k in keywords_status):
        status_filter = None
        if any(k in msg_lower for k in keywords_available):
            status_filter = "available"
        elif "reserved" in msg_lower or "محجوز" in msg_lower:
            status_filter = "reserved"
        elif "hold" in msg_lower:
            status_filter = "hold"

        if area_filter or status_filter or detected_project:
            units = get_all_units(project_filter=detected_project, status_filter=status_filter, area_filter=area_filter)
            title = "الوحدات"
            if status_filter:
                title += f" {status_filter}"
            if area_filter:
                title += f" ({area_filter}م²)"
            if detected_project:
                title += f" في {detected_project}"
            text = format_units(units, title)
            await update.message.reply_text(text, parse_mode="Markdown")
        else:
            results = get_project_status()
            text = format_status(results)
            await update.message.reply_text(f"📊 *ملخص المشاريع*\n\n{text}", parse_mode="Markdown")
        return

    project_info = get_project_info(detected_project) if detected_project else ""

    if "سكريبت" in msg_lower:
        user_context[user_id] = {"project": detected_project or "", "request": user_message}
        await update.message.reply_text(
            f"سكريبت {detected_project or ''} - اختر الأسلوب:",
            reply_markup=get_style_buttons()
        )
        return

    if "اعلان" in msg_lower or "إعلان" in msg_lower:
        system = f"""أنت خبير تسويق عقاري في معمار دجلة.
{COMPANY_INFO}
معلومات المشروع: {project_info}
اكتب 3 صيغ إعلانية بأسلوب مصري راقٍ.
لا تذكر أي اسم غير معمار دجلة."""
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )
        await update.message.reply_text(response.content[0].text)
        return

    add_to_history(user_id, "user", user_message)

    system = f"""أنت مساعد فريق مبيعات شركة معمار دجلة.
تتحدث بأسلوب مصري راقٍ وطبيعي. اسم الشركة دائماً "معمار دجلة" فقط.
جميع الوحدات إدارية أو تجارية أو طبية - لا توجد وحدات سكنية.
{COMPANY_INFO}
المشاريع: {", ".join(PROJECTS)}
{f"معلومات {detected_project}:{chr(10)}{project_info}" if project_info else ""}
إذا سأل - أجب بشكل طبيعي ومختصر."""

    history = get_history(user_id)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=system,
        messages=history
    )
    reply = response.content[0].text.strip()
    add_to_history(user_id, "assistant", reply)
    await update.message.reply_text(reply)

def main():
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
