#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
БОТ ДЛЯ МОНИТОРИНГА МЕСТ НА ВИЗУ В ИТАЛИЮ (VFS Global)
"""

import asyncio
import logging
import json
import os
import re
from datetime import datetime

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.exceptions import TelegramAPIError

# ============================================================
#  НАСТРОЙКИ (ВСТАВЛЕН НОВЫЙ ТОКЕН)
# ============================================================

BOT_TOKEN = "8497402362:AAGVZ8jHwbrdxZLTJmihLMDqjyYNziZuRBA"

# CHAT_ID будет определен автоматически при первом /start
URL = "https://services.vfsglobal.by/blr/ru/ita/api/application-detail"

CHECK_INTERVAL = 60  # Проверка каждые 60 секунд
STATE_FILE = "bot_state.json"

# ============================================================
#  ИНИЦИАЛИЗАЦИЯ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальные переменные
user_id = None  # ID пользователя, кто запустил бота
last_status = False  # Последний известный статус мест
is_monitoring = True  # Флаг мониторинга
first_run = True  # Флаг первого запуска


# ============================================================
#  ФУНКЦИИ ДЛЯ РАБОТЫ С СОСТОЯНИЕМ
# ============================================================

def load_state() -> dict:
    """Загружает сохраненное состояние из файла"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_state(data: dict) -> None:
    """Сохраняет состояние в файл"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass


# ============================================================
#  ФУНКЦИЯ ПРОВЕРКИ НАЛИЧИЯ МЕСТ
# ============================================================

async def check_availability() -> tuple[bool, str]:
    """
    Проверяет наличие свободных мест на странице VFS.
    Возвращает (есть_места, сообщение_об_ошибке)
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }

        response = requests.get(URL, headers=headers, timeout=15)
        response.raise_for_status()

        # Пытаемся прочитать как JSON
        try:
            data = response.json()
            text = str(data).lower()
        except:
            text = response.text.lower()

        # Признаки наличия мест
        positive_signals = [
            "available", "free", "свободн", "disponibile",
            "slot", "запись", "booking", "calendar"
        ]
        negative_signals = [
            "no availability", "нет мест", "занято",
            "fully booked", "no slots", "недоступно"
        ]

        has_positive = any(signal in text for signal in positive_signals)
        has_negative = any(signal in text for signal in negative_signals)

        # Если есть позитивный сигнал и нет негативного – места есть
        if has_positive and not has_negative:
            return True, None

        # Если есть даты в тексте – тоже вероятно есть места
        dates = re.findall(r'\b\d{2}[/-]\d{2}[/-]\d{4}\b', text)
        if dates:
            return True, None

        # Иначе считаем, что мест нет
        return False, None

    except requests.exceptions.Timeout:
        return False, "Превышено время ожидания ответа от сервера"
    except requests.exceptions.ConnectionError:
        return False, "Не удалось подключиться к серверу"
    except Exception as e:
        return False, f"Ошибка: {str(e)}"


# ============================================================
#  КОМАНДЫ БОТА
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    global user_id, is_monitoring

    user_id = message.from_user.id
    is_monitoring = True

    # Создаем клавиатуру
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Проверить сейчас")],
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="⏸ Пауза")],
            [KeyboardButton(text="▶️ Продолжить"), KeyboardButton(text="🔄 Перезапустить")]
        ],
        resize_keyboard=True
    )

    await message.answer(
        f"✅ **Бот запущен!**\n\n"
        f"📍 Мониторинг: VFS Global Italy (Минск)\n"
        f"⏱ Интервал проверки: {CHECK_INTERVAL} сек.\n"
        f"📨 Как только появятся места – я сообщу!\n\n"
        f"🔗 Ссылка: {URL}",
        reply_markup=keyboard
    )

    logger.info(f"✅ Пользователь {user_id} запустил бота")


@dp.message(Command("check"))
async def cmd_check(message: Message) -> None:
    global user_id
    user_id = message.from_user.id

    await message.answer("🔍 Проверяю наличие мест... Подождите пару секунд.")

    available, error = await check_availability()

    if error:
        await message.answer(f"❌ Ошибка при проверке: {error}")
        return

    now = datetime.now().strftime("%H:%M:%S")
    if available:
        await message.answer(
            f"✅ **ЕСТЬ СВОБОДНЫЕ МЕСТА!** 🎉\n"
            f"⏰ Время: {now}\n\n"
            f"🏃‍♂️ **СРОЧНО ЗАПИСЫВАЙСЯ!**\n"
            f"🔗 {URL}"
        )
    else:
        await message.answer(
            f"❌ **Свободных мест нет**\n"
            f"⏰ Время: {now}\n\n"
            f"Продолжаю мониторинг..."
        )


@dp.message(Command("status"))
async def cmd_status(message: Message) -> None:
    global user_id, last_status, is_monitoring
    user_id = message.from_user.id

    state = load_state()
    last_check = state.get("last_check", "неизвестно")
    found_count = state.get("found_count", 0)

    await message.answer(
        f"📊 **Текущий статус мониторинга:**\n\n"
        f"• Мониторинг: {'🟢 Активен' if is_monitoring else '⏸ Приостановлен'}\n"
        f"• Последний статус мест: {'✅ ЕСТЬ' if last_status else '❌ НЕТ'}\n"
        f"• Последняя проверка: {last_check}\n"
        f"• Всего найдено мест: {found_count}\n"
        f"• Интервал: {CHECK_INTERVAL} сек."
    )


@dp.message(Command("pause"))
async def cmd_pause(message: Message) -> None:
    global user_id, is_monitoring
    user_id = message.from_user.id
    is_monitoring = False
    await message.answer("⏸ Мониторинг приостановлен. Для возобновления нажмите '▶️ Продолжить' или /resume")


@dp.message(Command("resume"))
async def cmd_resume(message: Message) -> None:
    global user_id, is_monitoring
    user_id = message.from_user.id
    is_monitoring = True
    await message.answer("▶️ Мониторинг возобновлен!")


@dp.message(Command("restart"))
async def cmd_restart(message: Message) -> None:
    global user_id, is_monitoring, last_status
    user_id = message.from_user.id
    is_monitoring = True
    last_status = False
    await message.answer("🔄 Мониторинг перезапущен!")


# Обработка кнопок
@dp.message()
async def handle_buttons(message: Message) -> None:
    global user_id
    user_id = message.from_user.id

    if message.text == "🔍 Проверить сейчас":
        await cmd_check(message)
    elif message.text == "📊 Статус":
        await cmd_status(message)
    elif message.text == "⏸ Пауза":
        await cmd_pause(message)
    elif message.text == "▶️ Продолжить":
        await cmd_resume(message)
    elif message.text == "🔄 Перезапустить":
        await cmd_restart(message)


# ============================================================
#  ФОНОВЫЙ МОНИТОРИНГ
# ============================================================

async def monitoring_loop() -> None:
    global last_status, first_run, user_id

    await asyncio.sleep(5)
    logger.info("🟢 Мониторинг запущен!")

    while True:
        try:
            # Если мониторинг приостановлен или нет пользователя – ждем
            if not is_monitoring or user_id is None:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            # Проверяем наличие мест
            available, error = await check_availability()
            now = datetime.now()

            # Обновляем состояние
            state = load_state()
            state["last_check"] = now.strftime("%Y-%m-%d %H:%M:%S")
            state["last_status"] = available

            # Логируем
            status_text = "✅ ЕСТЬ" if available else "❌ НЕТ"
            logger.info(f"[{now.strftime('%H:%M:%S')}] Места: {status_text}")

            # Если места появились (было False, стало True) и это не первый запуск
            if available and not last_status and not first_run:
                state["found_count"] = state.get("found_count", 0) + 1

                try:
                    await bot.send_message(
                        user_id,
                        f"🚨🚨🚨\n"
                        f"🇮🇹 **ПОЯВИЛИСЬ СВОБОДНЫЕ МЕСТА!**\n"
                        f"⏰ {now.strftime('%H:%M:%S')}\n"
                        f"📅 {now.strftime('%d.%m.%Y')}\n\n"
                        f"🏃‍♂️ **СРОЧНО ЗАПИСЫВАЙСЯ!**\n\n"
                        f"🔗 {URL}\n\n"
                        f"⚠️ Места разбирают очень быстро!\n"
                        f"🚨🚨🚨"
                    )
                    logger.info("🔔 Уведомление отправлено!")
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления: {e}")

            # Обновляем глобальный статус
            last_status = available
            save_state(state)
            first_run = False

        except Exception as e:
            logger.error(f"Ошибка в цикле мониторинга: {e}")
            await asyncio.sleep(10)

        # Ждем до следующей проверки
        await asyncio.sleep(CHECK_INTERVAL)


# ============================================================
#  ЗАПУСК
# ============================================================

async def main() -> None:
    try:
        print("\n" + "=" * 50)
        print("✅ БОТ УСПЕШНО ЗАПУЩЕН!")
        print("=" * 50)
        print(f"📍 Мониторинг: VFS Global Italy (Минск)")
        print(f"⏱ Интервал проверки: {CHECK_INTERVAL} сек.")
        print("📨 Открой Telegram и напиши боту /start")
        print("=" * 50 + "\n")

        # Запускаем фоновый мониторинг
        asyncio.create_task(monitoring_loop())

        # Запускаем бота
        await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")