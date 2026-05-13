import asyncio
import json
from decimal import Decimal
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import httpx

# Конфигурация
BOT_TOKEN = "8714933043:AAHIP0WJk1SycaKYawxIpT555q1cR4yYlkg"
ADMIN_ID = 7518728008
SUPABASE_URL = "https://cpvgdwhcumzbjiurlemm.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwdmdkd2hjdW16YmppdXJsZW1tIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg1MjQ4MTksImV4cCI6MjA5NDEwMDgxOX0.kWU2RgofpNUnR74aYWJpw0OCU7c5taDtu69nlXircpM"

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Временное хранилище для связи файла с пользователем
file_user_map = {}

# Состояния FSM
class PaymentStates(StatesGroup):
    waiting_for_amount = State()

# HTTP клиент для Supabase REST API
async def supabase_query(method, table, data=None, filters=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    # Добавляем фильтры в URL
    if filters:
        params = []
        for key, value in filters.items():
            if key == "select":
                params.append(f"select={value}")
            elif key == "eq":
                for field, val in value.items():
                    params.append(f"{field}=eq.{val}")
        if params:
            url += "?" + "&".join(params)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            if method == "GET":
                response = await client.get(url, headers=headers)
            elif method == "POST":
                response = await client.post(url, headers=headers, json=data)
            elif method == "PATCH":
                response = await client.patch(url, headers=headers, json=data)
            
            if response.status_code in [200, 201]:
                return response.json() if response.text else []
            else:
                print(f"Supabase error: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            print(f"Request error: {e}")
            return []

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
    user_data = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "balance": 0.00
    }
    
    # Проверяем существует ли пользователь
    existing = await supabase_query("GET", "users", filters={
        "eq": {"user_id": message.from_user.id}
    })
    
    if not existing:
        await supabase_query("POST", "users", data=user_data)
    
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
    transaction_data = {
        "user_id": message.from_user.id,
        "file_name": message.document.file_name,
        "status": "pending",
        "amount": 0.00
    }
    await supabase_query("POST", "transactions", data=transaction_data)
    
    # Пересылаем файл админу
    await bot.send_document(
        ADMIN_ID,
        message.document.file_id,
        caption=f"📄 Файл от @{message.from_user.username or 'нет юзернейма'} (ID: {message.from_user.id})\nИмя: {message.from_user.first_name}",
        reply_markup=get_admin_keyboard(file_id)
    )
    
    await message.answer("✅ Файл загружен, ожидайте пополнение счета")

@dp.callback_query(F.data.startswith("block_"))
async def block_file(callback: types.CallbackQuery):
    file_id = callback.data.replace("block_", "")
    user_data = file_user_map.get(file_id)
    
    if user_data:
        # Обновляем статус транзакции
        await supabase_query("PATCH", "transactions", 
            data={"status": "blocked"},
            filters={"eq": {"user_id": user_data["user_id"], "status": "pending"}}
        )
        
        # Уведомляем пользователя
        await bot.send_message(user_data["user_id"], "❌ Блок, нет оплаты")
        
        # Обновляем сообщение админу
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
        await supabase_query("PATCH", "transactions",
            data={"status": "declined"},
            filters={"eq": {"user_id": user_data["user_id"], "status": "pending"}}
        )
        
        await bot.send_message(user_data["user_id"], "🔄 Всё слет, не оплата")
        
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
        
        # Получаем текущий баланс
        user_data = await supabase_query("GET", "users", filters={"eq": {"user_id": user_id}})
        current_balance = Decimal(str(user_data[0]["balance"])) if user_data else Decimal("0")
        new_balance = current_balance + amount
        
        # Обновляем баланс
        await supabase_query("PATCH", "users",
            data={"balance": float(new_balance)},
            filters={"eq": {"user_id": user_id}}
        )
        
        # Обновляем транзакцию
        await supabase_query("PATCH", "transactions",
            data={"status": "paid", "amount": float(amount)},
            filters={"eq": {"user_id": user_id, "status": "pending"}}
        )
        
        # Уведомляем пользователя
        await bot.send_message(
            user_id,
            f"✅ Ваш баланс пополнен на ${amount:.2f}\n💰 Текущий баланс: ${new_balance:.2f}"
        )
        
        await message.answer(f"✅ Баланс пользователя пополнен на ${amount:.2f}")
        await state.clear()
        
    except (ValueError, Exception) as e:
        await message.answer("❌ Пожалуйста, введите корректную сумму (например 5.50)")
        print(f"Error: {e}")

@dp.message(Command("balance"))
async def check_balance(message: types.Message):
    user_data = await supabase_query("GET", "users", filters={"eq": {"user_id": message.from_user.id}})
    if user_data:
        balance = Decimal(str(user_data[0]["balance"]))
        await message.answer(f"💰 Ваш баланс: ${balance:.2f}")
    else:
        await message.answer("💰 Ваш баланс: $0.00")

async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
