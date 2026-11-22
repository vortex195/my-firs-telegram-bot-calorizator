import asyncio
import logging
import os
import aiohttp
from dotenv import load_dotenv
from aiohttp import web



from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

# Загружаем секретные ключи из скрытого файла .env
load_dotenv()

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# =============================================

# Модель 3.5-flash-lite
MODEL_NAME = "models/gemini-3.5-flash-lite"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

SYSTEM_INSTRUCTION = """
Ты — точный калькулятор КБЖУ и состава продуктов.
Пользователь присылает название продукта. Рассчитай данные строго на 100 грамм продукта.

Правила расчета и оформления:
1. В графе углеводов оформляй как на пищевых упаковках: общее количество, а строкой ниже — «из них сахара».
2. Если в продукте содержится заметное количество клетчатки (авокадо, бобовые, отруби, овощи, семена и т.д.), обязательно укажи в графе "Углеводы" в скобках усвояемые (чистые) углеводы (Общие углеводы - Клетчатка).
3. В графе «Состав» укажи типичный состав продукта / ингредиенты (если это монопродукт вроде яблока или гречки — укажи это кратко, например: «100% гречневая крупа»).
4. Отвечай кратко, строго по шаблону, без вводных приветствий и лишних рассуждений.

Шаблон ответа:
🍽 [Название продукта] (на 100 г):
• Калории: X ккал
• Белки: X г
• Жиры: X г
• Углеводы: X г (усвояемые: X г — если актуально)
  └ из них сахара: X г
• Состав: [типичный состав / основные ингредиенты]
"""


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Напиши мне название любого продукта или блюда (например, <i>Сникерс</i> или <i>гречка</i>), "
        "и я пришлю расчет КБЖУ (с сахарами на 100 г) и состав продукта.",
        parse_mode="HTML",
    )


async def ask_gemini(prompt: str, retries: int = 3) -> str:
    model_path = MODEL_NAME if MODEL_NAME.startswith("models/") else f"models/{MODEL_NAME}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent"
    
    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "generationConfig": {
            "temperature": 0.2,
            # ВОТ ГЛАВНАЯ СТРОЧКА: Отключаем время на лишние "раздумья"
            "thinkingConfig": {
                "thinkingLevel": "medium"
            }
        }
    }

    # Таймаут на всякий случай
    timeout = aiohttp.ClientTimeout(total=30)

    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    
                    if resp.status == 200:
                
                        parts = data["candidates"][0]["content"]["parts"]
                        return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                    
                    if resp.status in (503, 429) and attempt < retries - 1:
                        await asyncio.sleep(1)
                        continue
                    
                    error_msg = data.get("error", {}).get("message", str(data))
                    raise Exception(f"Google API Error ({resp.status}): {error_msg}")
        except asyncio.TimeoutError:
            if attempt < retries - 1:
                continue
            raise Exception("Google не успел ответить вовремя, попробуй еще раз.")


@dp.message()
async def calculate_kbju(message: types.Message):
    if not message.text:
        return

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    prompt = f"Продукт: {message.text.strip()}"

    try:
        reply_text = await ask_gemini(prompt)
        await message.answer(reply_text)
    except Exception as e:
        logging.error(f"Ошибка при запросе: {e}")
        await message.answer(f"⚠️ Ошибка:\n<code>{e}</code>", parse_mode="HTML")


async def health_check(request):
    return web.Response(text="Bot is alive!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Веб-сервер запущен на порту {port}")


async def main():
    logging.basicConfig(level=logging.INFO)
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)

    print("Бот успешно запущен!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
