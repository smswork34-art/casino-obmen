import asyncio
import os
from decimal import Decimal
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from supabase import create_client, Client

# Конфигурация
BOT_TOKEN = "8714933043:AAHIP0WJk1SycaKYawxIpT555q1cR4yYlkg"
ADMIN_ID = 7518728008
SUPABASE_URL = "https://cpvgdwhcumzbjiurlemm.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwdmdkd2hjdW16YmppdXJsZW1tIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg1MjQ4MTksImV4cCI6MjA5NDEwMDgxOX0.kWU2RgofpNUnR74aYWJpw0OCU7c5taDtu69nlXircpM"

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Состояния
class PaymentStates(StatesGroup):
    waiting_for_amount = State()

# Временное хранилище для связи файла с пользователем
file_user_map = {}

# Клавиатуры
def get_start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Загрузить токены", callback_data="upload_tokens")]
    ])

def get_admin_keyboard(file_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Блок", callback_data=f"block_{file_id}")],
        [InlineKeyboardButton(text="💰 Ввести кол-во оплаты", callback_data=f"amount_{file_id}")],
        [InlineKeyboardButton(text="🔄 Слет все сразу", callback_data=f"decline_{file_id}")]
    ])

# Обработчики
@dp.message(Command("start"))
async def start_command(message: types.Message):
    # Сохраняем пользователя в БД
    try:
        supabase.table("users").upsert({
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name
        }).execute()
    except Exception as e:
        print(f"Error saving user: {e}")
    
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я бот для приёмки токенов MAX на RENDER.\n"
        "Нажми кнопку ниже, чтобы загрузить файл с токенами.",
        reply_markup=get_start_keyboard()
    )

@dp.callback_query(F.data == "upload_tokens")
async def upload_tokens(callback: types.CallbackQuery):
    await callback.message.answer("📎 Пожалуйста, загрузите файл токенов в формате .txt")
    await callback.answer()

@dp.message(F.document)
async def handle_document(message: types.Message):
    if not message.document.file_name.endswith('.txt'):
        await message.answer("❌ Пожалуйста, загрузите файл в формате .txt")
        return
    
    # Сохраняем связь файла с пользователем
    file_id = message.document.file_id
    file_user_map[file_id] = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "file_name": message.document.file_name
    }
    
    # Создаем транзакцию в БД
    try:
        supabase.table("transactions").insert({
            "user_id": message.from_user.id,
            "file_name": message.document.file_name,
            "status": "pending",
            "amount": 0
        }).execute()
    except Exception as e:
        print(f"Error creating transaction: {e}")
    
    # Пересылаем файл админу
    await bot.send_document(
        ADMIN_ID,
        message.document.file_id,
        caption=f"📄 Файл от @{message.from_user.username or 'нет юзернейма'} "
                f"(ID: {message.from_user.id})\n"
                f"Имя: {message.from_user.first_name}",
        reply_markup=get_admin_keyboard(file_id)
    )
    
    await message.answer("✅ Файл загружен, ожидайте пополнение счета")

@dp.callback_query(F.data.startswith("block_"))
async def block_file(callback: types.CallbackQuery):
    file_id = callback.data.replace("block_", "")
    user_data = file_user_map.get(file_id)
    
    if user_data:
        # Обновляем статус в БД
        supabase.table("transactions").update({"status": "blocked"}).eq(
            "user_id", user_data["user_id"]
        ).eq("status", "pending").execute()
        
        # Отправляем уведомление пользователю
        await bot.send_message(
            user_data["user_id"],
            "❌ Блок, нет оплаты"
        )
        
        await callback.message.edit_caption(
            callback.message.caption + "\n\n❌ ЗАБЛОКИРОВАНО",
            reply_markup=None
        )
    
    await callback.answer("Файл заблокирован")

@dp.callback_query(F.data.startswith("decline_"))
async def decline_file(callback: types.CallbackQuery):
    file_id = callback.data.replace("decline_", "")
    user_data = file_user_map.get(file_id)
    
    if user_data:
        # Обновляем статус в БД
        supabase.table("transactions").update({"status": "declined"}).eq(
            "user_id", user_data["user_id"]
        ).eq("status", "pending").execute()
        
        await bot.send_message(
            user_data["user_id"],
            "🔄 Всё слет, не оплата"
        )
        
        await callback.message.edit_caption(
            callback.message.caption + "\n\n🔄 СЛЕТ",
            reply_markup=None
        )
    
    await callback.answer("Файл отклонён")

@dp.callback_query(F.data.startswith("amount_"))
async def set_amount(callback: types.CallbackQuery, state: FSMContext):
    file_id = callback.data.replace("amount_", "")
    user_data = file_user_map.get(file_id)
    
    if user_data:
        await state.update_data(current_file_id=file_id, current_user_id=user_data["user_id"])
        await state.set_state(PaymentStates.waiting_for_amount)
        await callback.message.answer("💰 Введите сумму оплаты в долларах (например 5.50):")
    
    await callback.answer()

@dp.message(PaymentStates.waiting_for_amount)
async def process_amount(message: types.Message, state: FSMContext):
    try:
        amount = Decimal(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
        
        data = await state.get_data()
        user_id = data["current_user_id"]
        file_id = data["current_file_id"]
        
        # Обновляем баланс пользователя
        current_user = supabase.table("users").select("balance").eq("user_id", user_id).execute()
        if current_user.data:
            new_balance = Decimal(str(current_user.data[0]["balance"])) + amount
        else:
            new_balance = amount
        
        # Обновляем в БД
        supabase.table("users").update({"balance": float(new_balance)}).eq("user_id", user_id).execute()
        supabase.table("transactions").update({
            "status": "paid",
            "amount": float(amount)
        }).eq("user_id", user_id).eq("status", "pending").execute()
        
        # Уведомляем пользователя
        await bot.send_message(
            user_id,
            f"✅ Ваш баланс пополнен на ${amount:.2f}\n"
            f"💰 Текущий баланс: ${new_balance:.2f}"
        )
        
        await message.answer(f"✅ Баланс пользователя пополнен на ${amount:.2f}")
        await state.clear()
        
    except (ValueError, Decimal.InvalidOperation):
        await message.answer("❌ Пожалуйста, введите корректную сумму (например 5.50)")

@dp.message(Command("balance"))
async def check_balance(message: types.Message):
    try:
        result = supabase.table("users").select("balance").eq("user_id", message.from_user.id).execute()
        if result.data:
            balance = Decimal(str(result.data[0]["balance"]))
            await message.answer(f"💰 Ваш баланс: ${balance:.2f}")
        else:
            await message.answer("💰 Ваш баланс: $0.00")
    except Exception as e:
        await message.answer("❌ Ошибка при получении баланса")

async def main():
    # Создаем таблицы при первом запуске (если нужно)
    try:
        supabase.table("users").select("count").limit(1).execute()
    except:
        print("Таблицы не найдены. Создайте их в Supabase SQL Editor")
    
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
