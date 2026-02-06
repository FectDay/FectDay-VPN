import os
import json
import logging
from uuid import uuid4
from datetime import datetime
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)

#Конфиг
from config import TOKEN, ADMIN_IDS, MAX_BETA

#Пути
BASE_DIR = os.getcwd()
DATA_DIR = os.path.join(BASE_DIR, "u")
os.makedirs(DATA_DIR, exist_ok=True)

#Статусы или состояния
WAITING_FOR_REASON = 1
WAITING_FOR_CONFIG = 2

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

#Транслит first name пользователя тг если оно у него написано на кириллице (видно только у тех у кого есть физический доступ к серверу и его хранилищу)
CYR_TO_LAT = {
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'E', 'Ж': 'Zh',
    'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M', 'Н': 'N', 'О': 'O',
    'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts',
    'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch', 'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya',
}

def translit_name(name: str) -> str:
    if not name:
        return "user"
    out = []
    for ch in name:
        if 'а' <= ch <= 'я' or 'А' <= ch <= 'Я' or ch in ('ё', 'Ё'):
            up = ch.upper()
            lat = CYR_TO_LAT.get(up, '')
            out.append(lat)
        else:
            out.append(ch)
    res = ''.join(out)
    res = re.sub(r'[^A-Za-z0-9_-]', '', res)
    return res or 'user'

#Файлы пользователей

def user_file_path(first_name: str, tg_id: int) -> str:
    base = translit_name(first_name)
    return os.path.join(DATA_DIR, f"{base}_{tg_id}.db")


def save_user_data(tg_id: int, first_name: str, last_name: str, username: str):
    path = user_file_path(first_name or 'user', tg_id)
    data = {
        'tg_id': tg_id,
        'first_name': first_name or '',
        'last_name': last_name or '',
        'username': username or '',
        'status': 'pending',
        'applied_at': datetime.utcnow().isoformat() + 'Z',
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_user_data_by_id(tg_id: int):
    for fname in os.listdir(DATA_DIR):
        if fname.endswith(f"_{tg_id}.db"):
            p = os.path.join(DATA_DIR, fname)
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f), p
    return None, None


def update_user_data_file(path: str, patch: dict):
    if not os.path.exists(path):
        return
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    data.update(patch)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def count_approved_users():
    count = 0
    for fname in os.listdir(DATA_DIR):
        if fname.endswith('.db'):
            try:
                with open(os.path.join(DATA_DIR, fname), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data.get('status') == 'approved' and int(data.get('tg_id', 0)) not in ADMIN_IDS:
                        count += 1
            except Exception:
                pass
    return count

#Хэндлеры или же проще просто команды

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """Привет! Это бот регистрации на бета-тест VPN.
/apply — подать заявку
/status — статус
/slots — свободные места"""
    )


# NEW Теперь apply запускает диалог: спрашиваем причину
async def apply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Зачем вам нужен VPN? Коротко опишите цель использования.")
    return WAITING_FOR_REASON


# NEW Принимаем причину, сохраняем заявку и шлём админам
async def receive_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    reason = update.message.text.strip()

    existing, _ = load_user_data_by_id(user.id)
    if existing:
        await update.message.reply_text("Заявка уже подана, ожидайте решения админов.")
        return ConversationHandler.END

    path = save_user_data(user.id, user.first_name, user.last_name, user.username)
    update_user_data_file(path, {'reason': reason})

    await update.message.reply_text("Спасибо, заявка отправлена администраторам на рассмотрение.")

    text = (
        f"Новая заявка на бета-тест\n"
        f"User: {user.full_name}\n"
        f"Username: @{user.username if user.username else '-'}\n"
        f"TG ID: {user.id}\n\n"
        f"Для чего VPN:\n{reason}"
    )

    kb = InlineKeyboardMarkup([[ 
        InlineKeyboardButton("✅ Approve", callback_data=f"admin:approve:{user.id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"admin:reject:{user.id}")
    ]])

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text, reply_markup=kb)
        except Exception as e:
            logger.error(f"Failed to send admin notification to {admin_id}: {e}")

    return ConversationHandler.END


async def slots_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    approved = count_approved_users()
    left = max(0, MAX_BETA - approved)
    await update.message.reply_text(f"Занято: {approved}. Свободно: {left}.")


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3:
        await query.edit_message_text("Неправильный callback data")
        return
    _, action, target = parts

    try:
        target_id = int(target)
    except Exception:
        await query.edit_message_text("Неправильный ID")
        return

    if update.effective_user.id not in ADMIN_IDS:
        await query.edit_message_text("Только админ может принять решение.")
        return

    user_data, path = load_user_data_by_id(target_id)
    if not user_data:
        await query.edit_message_text("Данные пользователя не найдены (возможно устарели)")
        return

    if action == 'approve':
        if count_approved_users() >= MAX_BETA:
            await query.edit_message_text("Лимит слотов исчерпан.")
            try:
                await context.bot.send_message(target_id, "К сожалению, все слоты заняты. Попробуйте позже.")
            except Exception:
                pass
            return

        vpn_key = str(uuid4())
        update_user_data_file(path, {
            'status': 'approved',
            'vpn_key': vpn_key,
            'approved_at': datetime.utcnow().isoformat() + 'Z',
            'approved_by': update.effective_user.id,
        })

        await context.bot.send_message(target_id, f"Вы одобрены! Вскоре с вами свяжется менеджер или другой представитель для дальнейшей работы.", parse_mode='Markdown')
        await query.edit_message_text("Пользователь одобрен.")

    elif action == 'reject':
        update_user_data_file(path, {
            'status': 'rejected',
            'rejected_by': update.effective_user.id,
            'rejected_at': datetime.utcnow().isoformat() + 'Z'
        })
        await context.bot.send_message(target_id, "К сожалению ваша заявка отклонена.. У вас еще будет шанс! Если считаете это ошибкой, обратитесь на help@malikof.com")
        await query.edit_message_text("Пользователь отклонён.")


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud, _ = load_user_data_by_id(update.effective_user.id)
    if not ud:
        await update.message.reply_text("Вы ещё не подавали заявку.")
        return
    await update.message.reply_text(json.dumps(ud, ensure_ascii=False, indent=2))


#Главный/основной раздел

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler('start', start_handler))

    # Conversation для /apply -> вопрос -> ответ
    conv = ConversationHandler(
        entry_points=[CommandHandler('apply', apply_handler)],
        states={
            WAITING_FOR_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_reason)],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    app.add_handler(conv)

    app.add_handler(CommandHandler('slots', slots_handler))
    app.add_handler(CommandHandler('status', status_handler))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern=r'^admin:'))

    logger.info("Bot started")
    app.run_polling()


if __name__ == '__main__':
    main()
