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
    projects_list = "\n".join([f"{i+1}. {p}" for i, p in enumerate(PROJECTS)])
    await update.message.reply_text(f"اهلا! ana mosa3ed el sales\n\n{projects_list}\n\nEkteb esm el mashro3 w so2alek")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    project_data = ""
    detected_project = ""
    for p in PROJECTS:
        if p.lower() in user_message.lower():
            project_data = get_project_data(p)
            detected_project = p
            break

    if project_data:
        system = f"You are a real estate sales assistant. Project {detected_project} info:\n{project_data}\nAnswer in Arabic naturally and briefly."
    else:
        system = "You are a real estate sales assistant. Ask the user to specify which project they need info about."

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": user_message}]
    )
    await update.message.reply_text(response.content[0].text)

def main():
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
