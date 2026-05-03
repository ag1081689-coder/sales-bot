import os
import json
import anthropic
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

SHEET_ID = "1x5CfKVrgXZy1-1yVPoqAwcS0KpxeOyzxfA8shDt2qkw"
AV_SHEET_ID = "1f-1lkgr7nGiQofoREnhfbszjaJFu17OtZaMJ09_sLWw"
PROJECTS = ["D11 BUSINESS", "D12 Medical", "Metro Degla", "Medist", "Tigan", "WW1", "WW2", "STAGE X", "RESALE", "MIDST", "TIJAN"]
AV_PROJECTS = ["WW1", "WW2", "D11 BUSINESS", "D12 Medical", "TIJAN", "MIDST", "STAGE X", "RESALE"]
SECRET_PASSWORD = os.environ.get("SECRET_PASSWORD", "Adel2026")

COMPANY_INFO = """
معمار دجلة للتطوير العقاري - MEMAAR DEGLA DEVELOPMENT
تأسست: 2019 في العاشر من رمضان
فريق: أكثر من 65 متخصص
التمويل: ذاتي بالكامل
الموقع: memaardegla.com | 15409

المؤسسون:
- أ/ أحمد عبد العزيز
- م/ معاذ باشا
- أ/ محمد خليل

المشاريع المنفذة:
1. Degla One Mall (2019-2021) - 48 وحدة (25 تجاري + 11 إداري + 12 سكني)
2. Sky Degla Mall (2020-2023) - 233 وحدة (116 تجاري + 78 إداري + 39 طبي)

المشاريع قيد التنفيذ:
3. Metro Degla - 396 وحدة (231 تجاري + 87 إداري + 78 طبي)
4. Stage X - 96 وحدة تجارية
5. Midst Degla Mall - 99 وحدة (54 تجاري + 45 طبي)
6. Tijan Mall - 136 وحدة (76 تجاري + 20 إداري + 40 طبي)
7. Metro Plus Mall - 163 وحدة (91 تجاري + 48 إداري + 24 طبي)
8. Waterway Degla Mall - 188 وحدة (95 تجاري + 54 إداري + 39 طبي)

مزايا الشركة:
- أول شركة تغير الطابع العمراني التقليدي للعاشر من رمضان
- مواقع استراتيجية بحركة سكانية مرتفعة
- التزام بالتسليم طبقاً للمواصفات
- سمعة ممتازة داخل وخارج المدينة
"""

creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
gc = gspread.service_account_from_dict(creds_json)
sh = gc.open_by_key(SHEET_ID)
av_sh = gc.open_by_key(AV_SHEET_ID)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

user_context = {}
chat_history = {}

def get_availability_data():
   try:
       all_data = []
       for ws in av_sh.worksheets():
           try:
               data = ws.get_all_values()
               if len(data) < 3:
                   continue
               for row in data[3:]:
                   if len(row) >= 8 and row[2]:
                       unit = {
                           "sheet": ws.title,
                           "unit": row[2] if len(row) > 2 else "",
                           "area": row[3] if len(row) > 3 else "",
                           "price": row[4] if len(row) > 4 else "",
                           "total": row[5] if len(row) > 5 else "",
                           "project": row[6] if len(row) > 6 else "",
                           "status": row[7] if len(row) > 7 else "",
                           "down_payment": row[8] if len(row) > 8 else "",
                           "instalments": row[9] if len(row) > 9 else "",
                           "cash_discount": row[10] if len(row) > 10 else ""
                       }
                       all_data.append(unit)
           except:
               continue
       return all_data
   except:
       return []

def get_summary_and_details(project_filter=None):
   all_data = get_availability_data()
   available = [u for u in all_data if u["status"].lower() == "available"]
   if project_filter:
       available = [u for u in available if project_filter.lower() in u["sheet"].lower() or project_filter.lower() in u["project"].lower()]

   summary = {}
   for u in available:
       key = u["sheet"]
       if key not in summary:
           summary[key] = []
       summary[key].append(u)

   summary_text = "ملخص الوحدات المتاحة في معمار دجلة:\n\n"
   for project, units in summary.items():
       summary_text += f"• {project}: {len(units)} وحدة\n"
   summary_text += "\nللتفاصيل اكتب: تفاصيل [اسم المشروع]"
   return summary_text, summary

def get_project_details(project_filter):
   all_data = get_availability_data()
   available = [u for u in all_data if u["status"].lower() == "available" and (project_filter.lower() in u["sheet"].lower() or project_filter.lower() in u["project"].lower())]
   if not available:
       return f"لا توجد وحدات متاحة في {project_filter} حالياً."
   result = f"الوحدات المتاحة في {project_filter}:\n\n"
   for u in available:
       result += f"• {u['unit']} | {u['area']}م² | إجمالي {u['total']} جنيه | مقدم {u['down_payment']}\n"
   return result

def get_or_create_sheet(project):
   try:
       ws = sh.worksheet(project)
   except:
       ws = sh.add_worksheet(title=project, rows=1000, cols=10)
       ws.append_row(["سؤال", "جواب", "اسم الوحدة", "عدد الامتار", "سعر المتر"])
   return ws

def write_unit_to_sheet(project, unit_name, meters, price_per_meter):
   try:
       ws = get_or_create_sheet(project)
       data = ws.get_all_values()
       for i, row in enumerate(data):
           if len(row) >= 3 and row[2].strip() == unit_name.strip():
               ws.update_cell(i+1, 3, unit_name)
               ws.update_cell(i+1, 4, meters)
               ws.update_cell(i+1, 5, price_per_meter)
               return True
       ws.insert_row(["", "", unit_name, meters, price_per_meter], 2)
       return True
   except:
       return False

def write_to_sheet(project, field, value):
   try:
       ws = get_or_create_sheet(project)
       data = ws.get_all_values()
       for i, row in enumerate(data):
           if row and row[0].strip() == field.strip():
               ws.update_cell(i+1, 2, value)
               return True
       ws.append_row([field, value])
       return True
   except:
       return False

def get_project_data(project_name):
   try:
       ws = sh.worksheet(project_name)
       data = ws.get_all_values()
       result = ""
       units = []
       for row in data[1:]:
           if len(row) >= 2 and row[0] and row[1]:
               result += f"{row[0]}: {row[1]}\n"
           if len(row) >= 5 and row[2]:
               units.append(f"وحدة {row[2]}: {row[3]} متر - {row[4]} جنيه للمتر")
       if units:
           result += "\nالوحدات:\n" + "\n".join(units)
       return result
   except:
       return ""

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
   "style_pain": ("Pain Point", "ابدأ بمشكلة العميل وألمه، وريه إن المشروع ده هو الحل"),
   "style_compare": ("المقارنة", "قارن بين الإيجار والشراء بالأرقام الحقيقية"),
   "style_fomo": ("FOMO", "ضغط الوقت والندرة بأسلوب راقي"),
   "style_roi": ("ROI والأرقام", "احسبله العائد والأرقام بشكل واضح"),
   "style_story": ("القصة", "قصة عميل حقيقي نجح واستفاد"),
   "style_social": ("Social Proof", "أرقام مبيعات وشهادات موثوقة"),
   "style_exclusive": ("Exclusivity", "الحصرية والندرة وإن مش للكل")
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
       "أنا مساعدك في فريق المبيعات، يمكنني مساعدتك في:\n"
       "• الاستفسار عن الوحدات المتاحة\n"
       "• إنشاء إعلانات وسكريبتات احترافية\n"
       "• تسجيل المبيعات ومعلومات المشاريع\n\n"
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
   project_data = get_project_data(project) if project else ""

   system = f"""أنت خبير تسويق عقاري في شركة معمار دجلة.
معلومات الشركة: {COMPANY_INFO}
معلومات المشروع: {project_data}
تفاصيل العميل: {request}
الأسلوب: {style_name} - {style_instruction}
اكتب سكريبت واتساب بأسلوب مصري راقٍ وطبيعي.
- افتتاحية تشد الانتباه
- معلومات المشروع بشكل سلس
- نهاية تدفعه للتواصل
- لا تذكر أي اسم غير معمار دجلة"""

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

   if user_context.get(user_id, {}).get("waiting_password"):
       if user_message == SECRET_PASSWORD:
           user_context[user_id]["waiting_password"] = False
           user_context[user_id]["authenticated"] = True
           sales = get_sales_data()
           await update.message.reply_text(f"سجل المبيعات:\n\n{sales}")
       else:
           await update.message.reply_text("كلمة المرور غير صحيحة.")
       return

   if "مبيعات" in user_message or "بايعين" in user_message or "احنا بعنا" in user_message:
       if user_context.get(user_id, {}).get("authenticated"):
           sales = get_sales_data()
           await update.message.reply_text(f"سجل المبيعات:\n\n{sales}")
       else:
           user_context[user_id] = {"waiting_password": True}
           await update.message.reply_text("من فضلك أدخل كلمة المرور:")
       return

   if "بيعة" in user_message or "بعنا" in user_message or "اتباع" in user_message:
       system = """استخرج من الرسالة معلومات البيعة وأرجع JSON فقط:
{"action":"sale","project":"اسم المشروع","unit":"الوحدة","price":"السعر","client":"اسم العميل"}"""
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
                   f"المشروع: {data['project']}\n"
                   f"الوحدة: {data['unit']}\n"
                   f"السعر: {data['price']}\n"
                   f"العميل: {data['client']}"
               )
           return
       except:
           pass

   if "تفاصيل" in user_message:
       for p in AV_PROJECTS:
           if p.lower() in user_message.lower():
               details = get_project_details(p)
               await update.message.reply_text(details)
               return

   keywords_av = ["متاح", "available", "فاضي", "كام وحدة", "وحدات متاحة", "ايه المتاح", "المتاح", "الاتاحه", "الإتاحة"]
   if any(k in user_message.lower() for k in keywords_av):
       project_filter = None
       for p in AV_PROJECTS:
           if p.lower() in user_message.lower():
               project_filter = p
               break
       if not project_filter:
           for alias, real in [("d12", "D12 Medical"), ("d11", "D11 BUSINESS"), ("waterway", "WW"), ("ww1", "WW1"), ("ww2", "WW2"), ("tijan", "TIJAN"), ("midst", "MIDST"), ("stage x", "STAGE X")]:
               if alias in user_message.lower():
                   project_filter = real
                   break
       if project_filter:
           details = get_project_details(project_filter)
           await update.message.reply_text(details)
       else:
           summary, _ = get_summary_and_details()
           await update.message.reply_text(summary)
       return

   project_data = ""
   detected_project = ""
   for p in PROJECTS:
       if p.lower() in user_message.lower():
           project_data = get_project_data(p)
           detected_project = p
           break
   if not detected_project:
       aliases = {"d12": "D12 Medical", "d11": "D11 BUSINESS", "waterway": "WW1", "ww1": "WW1", "ww2": "WW2", "tijan": "TIJAN", "midst": "MIDST", "stage x": "STAGE X"}
       for alias, real in aliases.items():
           if alias in user_message.lower():
               detected_project = real
               project_data = get_project_data(real)
               break

   if "وحدة" in user_message and detected_project:
       system = """استخرج من الرسالة معلومات الوحدة وأرجع JSON فقط:
{"action":"unit","project":"اسم المشروع","unit_name":"اسم الوحدة","meters":"المساحة","price_per_meter":"سعر المتر"}"""
       response = client.messages.create(
           model="claude-haiku-4-5-20251001",
           max_tokens=200,
           system=system,
           messages=[{"role": "user", "content": user_message}]
       )
       reply = response.content[0].text.strip()
       try:
           data = json.loads(reply[reply.find("{"):reply.rfind("}")+1])
           if data.get("action") == "unit":
               write_unit_to_sheet(data["project"], data["unit_name"], data["meters"], data["price_per_meter"])
               await update.message.reply_text(
                   f"✅ تم إضافة الوحدة\n"
                   f"الوحدة: {data['unit_name']}\n"
                   f"المساحة: {data['meters']} م²\n"
                   f"سعر المتر: {data['price_per_meter']} جنيه"
               )
           return
       except:
           pass

   if "سكريبت" in user_message:
       user_context[user_id] = {"project": detected_project, "request": user_message}
       await update.message.reply_text(
           f"سكريبت {detected_project} - اختر الأسلوب:",
           reply_markup=get_style_buttons()
       )
       return

   if "اعلان" in user_message or "إعلان" in user_message:
       system = f"""أنت خبير تسويق عقاري في معمار دجلة.
معلومات الشركة: {COMPANY_INFO}
معلومات المشروع: {project_data}
اكتب 3 صيغ إعلانية مختلفة بأسلوب مصري راقٍ.
كل إعلان: افتتاحية جذابة + معلومات + call to action.
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

   av_context = ""
   if detected_project:
       units = get_project_details(detected_project)
       av_context = f"\nالوحدات المتاحة:\n{units}"

   system = f"""أنت مساعد فريق مبيعات شركة معمار دجلة للتطوير العقاري.
تتحدث بأسلوب مصري راقٍ وطبيعي.
اسم الشركة دائماً "معمار دجلة" فقط.

معلومات الشركة:
{COMPANY_INFO}

المشاريع في النظام: {", ".join(PROJECTS)}
{f"معلومات {detected_project}:{chr(10)}{project_data}" if project_data else ""}
{av_context}

إذا أراد إضافة معلومة - أرجع JSON فقط:
{{"action":"save","project":"اسم","fields":[{{"field":"حقل","value":"قيمة"}}]}}
إذا سأل - أجب بشكل طبيعي ومختصر متذكرا سياق المحادثة."""

   history = get_history(user_id)

   response = client.messages.create(
       model="claude-haiku-4-5-20251001",
       max_tokens=800,
       system=system,
       messages=history
   )
   reply = response.content[0].text.strip()

   add_to_history(user_id, "assistant", reply)

   if '"action"' in reply and '"save"' in reply:
       try:
           data = json.loads(reply[reply.find("{"):reply.rfind("}")+1])
           if data.get("action") == "save":
               project = data.get("project")
               for f in data.get("fields", []):
                   write_to_sheet(project, f["field"], f["value"])
               await update.message.reply_text(f"✅ تم حفظ المعلومات في {project}")
           return
       except:
           pass

   await update.message.reply_text(reply)

def main():
   app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
   app.add_handler(CommandHandler("start", start))
   app.add_handler(CallbackQueryHandler(handle_callback))
   app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
   app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
   main()
