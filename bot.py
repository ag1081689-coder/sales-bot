import os
import json
import anthropic
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

SHEET_ID = "1x5CfKVrgXZy1-1yVPoqAwcS0KpxeOyzxfA8shDt2qkw"
PROJECTS = ["D11", "D12", "Metro Degla", "Medist", "Tigan", "Waterway 1", "Waterway 2", "Stage X"]

creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
gc = gspread.service_account_from_dict(creds_json)
sh = gc.open_by_key(SHEET_ID)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

user_context = {}

def write_to_sheet(project, field, value):
   try:
       ws = sh.worksheet(project)
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
       for row in data:
           if len(row) >= 2:
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
   "style_pain": ("Pain Point", "ابدأ بمشكلة العميل وألمه، وريه إن المشروع ده هو الحل"),
   "style_compare": ("المقارنة", "قارن بين الإيجار والشراء بالأرقام الحقيقية"),
   "style_fomo": ("FOMO", "ضغط الوقت والندرة بأسلوب راقي"),
   "style_roi": ("ROI والأرقام", "احسبله العائد والأرقام بشكل واضح"),
   "style_story": ("القصة", "قصة عميل حقيقي نجح واستفاد"),
   "style_social": ("Social Proof", "أرقام مبيعات وشهادات موثوقة"),
   "style_exclusive": ("Exclusivity", "الحصرية والندرة وإن مش للكل")
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
   await update.message.reply_text("اهلا يسطا! انا مساعد السيلز، اسألني عن اي مشروع او قولي اكتب اعلان او سكريبت واسم المشروع")

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
   
   system = f"""انت كونتنت كرييتور متخصص في العقارات المصرية.
اكتب سكريبت واتساب احترافي وشيك بالعربية البسيطة الطبيعية.

معلومات المشروع:
{project_data}

تفاصيل العميل: {request}

الأسلوب المطلوب: {style_name} - {style_instruction}

قواعد الكتابة:
- Hook يخطف الانتباه في السطر الأول
- جسم الرسالة فيه المعلومات بشكل طبيعي مش ممل
- نهاية تخليه ياخد اكشن
- الأسلوب شيك ومحترم يليق بالعقارات
- مش طويل ومش قصير - مناسب لواتساب
- بدون مبالغة أو كلام فاضي"""

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

   project_data = ""
   detected_project = ""
   for p in PROJECTS:
       if p.lower() in user_message.lower():
           project_data = get_project_data(p)
           detected_project = p
           break

   if "سكريبت" in user_message:
       user_context[user_id] = {
           "project": detected_project,
           "request": user_message
       }
       await update.message.reply_text(
           f"تمام! سكريبت {detected_project} - اختار الأسلوب:",
           reply_markup=get_style_buttons()
       )
       return

   if "اعلان" in user_message or "إعلان" in user_message:
       system = f"""انت كونتنت كرييتور متخصص في العقارات المصرية.
اكتب 3 صيغ إعلانية مختلفة بالعامية المصرية الشيك.
معلومات المشروع: {project_data}
كل إعلان فيه hook يخطف، معلومات المشروع، وcall to action قوي.
احترافي ويليق بالعقارات."""

       response = client.messages.create(
           model="claude-haiku-4-5-20251001",
           max_tokens=1200,
           system=system,
           messages=[{"role": "user", "content": user_message}]
       )
       await update.message.reply_text(response.content[0].text)
       return

   if '"action"' in user_message and '"save"' in user_message:
       pass

   system = f"""انت سيلز عقاري مصري محترف بتكلم زميلك بالعامية المصرية.
المشاريع: {", ".join(PROJECTS)}
{f"معلومات {detected_project}:{chr(10)}{project_data}" if project_data else ""}
لو بيدي معلومة جديدة - رد بـ JSON فقط:
{{"action":"save","project":"اسم","fields":[{{"field":"حقل","value":"قيمة"}}]}}
لو بيسأل - رد طبيعي بالعامية."""

   response = client.messages.create(
       model="claude-haiku-4-5-20251001",
       max_tokens=800,
       system=system,
       messages=[{"role": "user", "content": user_message}]
   )

   reply = response.content[0].text.strip()

   if '"action"' in reply and '"save"' in reply:
       try:
           start_idx = reply.find("{")
           end_idx = reply.rfind("}") + 1
           data = json.loads(reply[start_idx:end_idx])
           if data.get("action") == "save":
               project = data.get("project")
               fields = data.get("fields", [])
               for f in fields:
                   write_to_sheet(project, f["field"], f["value"])
               await update.message.reply_text(f"تم حفظ المعلومات في {project} ✅")
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
