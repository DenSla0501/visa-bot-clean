#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import json
import os
import re
from datetime import datetime
from aiohttp import web

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

# ============================================================
#  НАСТРОЙКИ
# ============================================================

BOT_TOKEN = "8497402362:AA6VZ6JHahbrdxZLJmhLMdG1YzIZuRBA"
URL = "https://services.vfsglobal.by/blr/ru/ita/api/application-detail"
CHECK_INTERVAL = 60
STATE_FILE = "bot_state.json"
PORT = int(os.environ.get("PORT", 10000))  # Render задаёт порт

# ============================================================
#  ИНИЦИАЛИЗАЦИЯ
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_chat_id = None
last_status = False
is_monitoring = True
first_run = True

# ============================================================
#  ВЕБ-СЕРВЕР (чтобы Render не усыплял)
# ============================================================

async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Веб-сервер запущен на порту {PORT}")

# ============================================================
#  ФУНКЦИИ МОНИТОРИНГА
# ============================================================

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(data: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

async def check_availability():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        response = requests.get(URL, headers=headers, timeout=15)
        if response.status_code == 200:
            text = response.text.lower()
            if "available" in text or "свободн" in text or "disponibile" in text:
                if "no availability" not in text and "нет мест" not in text:
                    return True, None
            dates = re.findall(r'\b\d{2}[/-]\d{2}[/-]\d{4}\b', text)
            if dates:
                return True, None
        return False, None
    except Exception as e:
        return False, str(e)

# ============================================================
#  КОМАНДЫ БОТА
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    global user_chat_id, is_monitoring
    user_chat_id = message.from_user.id
    is_monitoring = True
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Проверить")],
            [KeyboardButton(text="📊 Статус")],
            [KeyboardButton(text="⏸ Пауза"), KeyboardButton(text="▶️ Продолжить")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        f"✅ Бот запущен!\n📍 Мониторинг: VFS Global Italy\n⏱ Интервал: {CHECK_INTERVAL} сек.",
        reply_markup=keyboard
    )

@dp.message(Command("check"))
async def cmd_check(message: Message):
    global user_chat_id
    user_chat_id = message.from_user.id
    await message.answer("🔍 Проверяю...")
    available, error = await check_availability()
    if error:
        await message.answer(f"❌ Ошибка: {error}")
        return
    now = datetime.now().strftime("%H:%M:%S")
    if available:
        await message.answer(f"✅ **ЕСТЬ МЕСТА!** 🎉\n⏰ {now}")
    else:
        await message.answer(f"❌ Нет мест.\n⏰ {now}")

@dp.message(Command("status"))
async def cmd_status(message: Message):
    global user_chat_id, last_status, is_monitoring
    user_chat_id = message.from_user.id
    state = load_state()
    await message.answer(
        f"📊 **Статус:**\n• Мониторинг: {'🟢 Активен' if is_monitoring else '⏸ Приостановлен'}\n"
        f"• Места: {'✅ ЕСТЬ' if last_status else '❌ НЕТ'}\n"
        f"• Последняя проверка: {state.get('last_check', 'неизвестно')}"
    )

@dp.message(Command("pause"))
async def cmd_pause(message: Message):
    global user_chat_id, is_monitoring
    user_chat_id = message.from_user.id
    is_monitoring = False
    await message.answer("⏸ Мониторинг приостановлен")

@dp.message(Command("resume"))
async def cmd_resume(message: Message):
    global user_chat_id, is_monitoring
    user_chat_id = message.from_user.id
    is_monitoring = True
    await message.answer("▶️ Мониторинг возобновлен")

@dp.message()
async def handle_buttons(message: Message):
    global user_chat_id
    user_chat_id = message.from_user.id
    if message.text == "🔍 Проверить":
        await cmd_check(message)
    elif message.text == "📊 Статус":
        await cmd_status(message)
    elif message.text == "⏸ Пауза":
        await cmd_pause(message)
    elif message.text == "▶️ Продолжить":
        await cmd_resume(message)

# ============================================================
#  МОНИТОРИНГ В ФОНЕ
# ============================================================

async def monitoring_loop():
    global last_status, first_run, user_chat_id
    await asyncio.sleep(3)
    while True:
        try:
            if not is_monitoring or user_chat_id is None:
                await asyncio.sleep(CHECK_INTERVAL)
                continue
            available, error = await check_availability()
            now = datetime.now()
            state = load_state()
            state["last_check"] = now.strftime("%Y-%m-%d %H:%M:%S")
            state["last_status"] = available
            if available and not last_status and not first_run:
                try:
                    await bot.send_message(
                        user_chat_id,
                        f"🚨🚨🚨\n🇮🇹 **ПОЯВИЛИСЬ МЕСТА!**\n⏰ {now.strftime('%H:%M:%S')}\n🔗 {URL}"
                    )
                    logger.info("🔔 Уведомление отправлено!")
                except Exception as e:
                    logger.error(f"Ошибка отправки: {e}")
            last_status = available
            save_state(state)
            first_run = False
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await asyncio.sleep(10)
        await asyncio.sleep(CHECK_INTERVAL)

# ============================================================
#  ЗАПУСК
# ============================================================

async def main():
    try:
        # Запускаем веб-сервер
        asyncio.create_task(start_web_server())
        # Запускаем мониторинг
        asyncio.create_task(monitoring_loop())
        # Запускаем бота
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
