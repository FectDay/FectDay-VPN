import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties #1
from aiogram.enums import ParseMode #1
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, CallbackQuery
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from config import BOT_TOKEN, ADMIN_ID, CHANNEL_URL
from database import init_db, add_request, set_status
from texts import TEXTS

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
dp = Dispatcher()
init_db()

user_lang = {}

class Form(StatesGroup):
    name = State()
    country = State()
    device = State()
    purpose = State()

#Клавиатура типа
def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔄 Перезагрузить")],
            [KeyboardButton(text="ℹ️ О программе")],
            [KeyboardButton(text="📢 Канал FectDay")]
        ],
        resize_keyboard=True
    )

def lang_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="English", callback_data="lang_en"),
            InlineKeyboardButton(text="Русский", callback_data="lang_ru")
        ]
    ])

def menu_kb(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]["get"], callback_data="get_vpn")]
    ])

@dp.message(F.text == "/start")
@dp.message(F.text == "🔄 Перезагрузить")
async def start(m: Message):
    user_lang[m.from_user.id] = "en"
    await m.answer(TEXTS["en"]["start"], reply_markup=main_kb())
    await m.answer(TEXTS["en"]["choose_lang"], reply_markup=lang_kb())

@dp.message(F.text == "ℹ️ О программе")
async def about(m: Message):
    lang = user_lang.get(m.from_user.id, "en")
    await m.answer(TEXTS[lang]["about"])

@dp.message(F.text == "📢 Канал FectDay")
async def channel(m: Message):
    await m.answer(CHANNEL_URL)

@dp.callback_query(F.data.startswith("lang_"))
async def set_lang(cb: CallbackQuery):
    lang = cb.data.split("_")[1]
    user_lang[cb.from_user.id] = lang
    await cb.message.answer(TEXTS[lang]["menu"], reply_markup=menu_kb(lang))
    await cb.answer()

@dp.callback_query(F.data == "get_vpn")
async def start_form(cb: CallbackQuery, state: FSMContext):
    lang = user_lang.get(cb.from_user.id, "en")
    await cb.message.answer(TEXTS[lang]["name"])
    await state.set_state(Form.name)
    await cb.answer()

@dp.message(Form.name)
async def f_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    lang = user_lang[m.from_user.id]
    await m.answer(TEXTS[lang]["country"])
    await state.set_state(Form.country)

@dp.message(Form.country)
async def f_country(m: Message, state: FSMContext):
    await state.update_data(country=m.text)
    lang = user_lang[m.from_user.id]
    await m.answer(TEXTS[lang]["device"])
    await state.set_state(Form.device)

@dp.message(Form.device)
async def f_device(m: Message, state: FSMContext):
    await state.update_data(device=m.text)
    lang = user_lang[m.from_user.id]
    await m.answer(TEXTS[lang]["purpose"])
    await state.set_state(Form.purpose)

@dp.message(Form.purpose)
async def f_done(m: Message, state: FSMContext):
    data = await state.get_data()
    req_id = add_request((
        m.from_user.id,
        m.from_user.username,
        data["name"],
        data["country"],
        data["device"],
        m.text,
        "pending"
    ))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{req_id}_{m.from_user.id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{req_id}_{m.from_user.id}")
        ]
    ])

    await bot.send_message(
        ADMIN_ID,
        f"🆕 VPN REQUEST #{req_id}\n\n{data}\nPurpose: {m.text}",
        reply_markup=kb
    )

    lang = user_lang[m.from_user.id]
    await m.answer(TEXTS[lang]["wait"])
    await state.clear()

@dp.callback_query(F.data.startswith("approve_"))
async def approve(cb: CallbackQuery):
    _, req_id, user_id = cb.data.split("_")
    user_id = int(user_id)

    set_status(int(req_id), "approved")

    lang = user_lang.get(user_id, "en")
    await bot.send_message(user_id, TEXTS[lang]["approved"])
    await cb.answer("Approved")

@dp.callback_query(F.data.startswith("reject_"))
async def reject(cb: CallbackQuery):
    _, req_id, user_id = cb.data.split("_")
    user_id = int(user_id)

    set_status(int(req_id), "rejected")

    lang = user_lang.get(user_id, "en")
    await bot.send_message(user_id, TEXTS[lang]["rejected"])
    await cb.answer("Rejected")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
