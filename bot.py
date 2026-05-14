import asyncio
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

BOT_TOKEN = "8929020236:AAFQqymbnuXy001KGZKQL_iFQLJFSmGghgc"
RENDER_URL = "https://casino-obmen.onrender.com"
PORT = int(os.getenv("PORT", 10000))
GROUP_ID = -5182443833

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start(msg: types.Message):
    await msg.answer("Отправьте мне .txt файл — я перешлю его в группу.")

@dp.message(F.document)
async def handle_file(msg: types.Message):
    if not msg.document.file_name.endswith('.txt'):
        await msg.answer("Принимаются только .txt файлы.")
        return
    
    file = await bot.get_file(msg.document.file_id)
    file_path = file.file_path
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as resp:
            content = await resp.text()
    
    caption = f"Файл: {msg.document.file_name}\nОт: @{msg.from_user.username or msg.from_user.id}"
    await bot.send_document(GROUP_ID, msg.document.file_id, caption=caption)
    await msg.answer("Файл отправлен в группу.")

@dp.message()
async def echo(msg: types.Message):
    await msg.answer("Отправьте .txt файл для пересылки в группу.")

async def on_startup():
    await bot.set_webhook(f"{RENDER_URL}/webhook")

async def main():
    await on_startup()
    app = web.Application()
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
