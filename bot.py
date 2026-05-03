import os
import json
import anthropic
import gspread
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

SHEET_ID = "1x5CfKVrgXZy1-1yVPoqAwcS0KpxeOyzxfA8shDt2qkw"
PROJECTS = ["D11", "D12", "Metro Degla", "Medist", "Tigan", "Waterway 1", "Waterway 2", "Stage X"]

creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
gc = gspread.service_account_from_dict(creds_json)
sh = gc.open_by_key(SHEET_ID)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اهلا! انا مساعد السيلز، كلمني بشكل طبيعي واسألني عن اي مشروع او قولي اي معلومة تحب اسجلها")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()

    project_data = ""
    detected_project = ""
    for p in PROJECTS:
        if p.lower() in user_message.lower():
            project_data = get_project_data(p)
            detected_project = p
            break

    system = f"""انت مساعد سيلز عقاري مصري بتكلم زميلك السيلز بشكل طبيعي.

المشاريع المتاحة: {", ".join(PROJECTS)}

{f"المعلومات الموجودة عن {detected_project}:{chr(10)}{project_data}" if project_data else ""}

مهامك:
1. لو السيلز بيسأل عن مشروع - رد بالمعلومات الموجودة
2. لو السيلز بيقولك معلومة جديدة - استخرج منها: اسم المشروع، الحقل، القيمة وارجعلي JSON كده:
{{"action": "save", "project": "اسم المشروع", "fields": [{{"field": "اسم الحقل", "value": "القيمة"}}]}}
3. لو مش واضح - اسأل

رد بـ JSON لو في معلومات تتسجل، غير كده رد طبيعي بالعربي."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": user_message}]
    )

    reply = response.content[0].text.strip()

    if '{"action": "save"' in reply or '"action":"save"' in reply:
        try:
            start_idx = reply.find("{")
            end_idx = reply.rfind("}") + 1
            data = json.loads(reply[start_idx:end_idx])
            if data.get("action") == "save":
                project = data.get("project")
                fields = data.get("fields", [])
                saved = []
                for f in fields:
                    write_to_sheet(project, f["field"], f["value"])
                    saved.append(f["field"])
                await update.message.reply_text(f"تم حفظ {len(saved)} معلومة في {project} ✅")
            return
        except:
            pass

    await update.message.reply_text(reply)

def main():
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
