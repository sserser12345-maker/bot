import asyncio
import os
import tempfile
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiohttp import web
import yt_dlp

# Токен будем передавать через настройки Render (Environment Variables)
TOKEN = os.getenv("BOT_TOKEN")
dp = Dispatcher()

# Временное хранилище ссылок по ID сообщения
links_cache: dict[int, str] = {}


def download_mp3(url: str, out_dir: str) -> str:
  out_template = os.path.join(out_dir, "%(title)s.%(ext)s")
  ydl_opts = {
      "format": "bestaudio/best",
      "outtmpl": out_template,
      "noplaylist": True,
      "postprocessors": [
          {
              "key": "FFmpegExtractAudio",
              "preferredcodec": "mp3",
              "preferredquality": "192",
          }
      ],
  }
  with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(url, download=True)
    base_path = ydl.prepare_filename(info)
    mp3_path = os.path.splitext(base_path)[0] + ".mp3"
    return mp3_path


@dp.message(CommandStart())
async def cmd_start(message: Message):
  await message.answer(
      "Привет! Отправь мне ссылку на видео или аудио — я подготовлю кнопку для скачивания в MP3."
  )


@dp.message(F.text.regexp(r"https?://\S+"))
async def handle_link(message: Message):
  url = message.text.strip()
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="Скачать MP3", callback_data="dl_mp3"
              )
          ]
      ]
  )
  sent = await message.answer(
      f"Ссылка принята:\n{url}\n\nНажми кнопку ниже, чтобы получить MP3:",
      reply_markup=keyboard,
  )
  links_cache[sent.message_id] = url


@dp.callback_query(F.data == "dl_mp3")
async def on_download_mp3(callback: CallbackQuery):
  if not callback.message:
    return
  url = links_cache.get(callback.message.message_id)
  if not url:
    await callback.answer(
        "Ссылка устарела, отправь её заново.", show_alert=True
    )
    return

  await callback.answer("Начинаю обработку...")
  status_msg = await callback.message.answer(
      "Скачиваю и конвертирую в MP3, подожди..."
  )

  with tempfile.TemporaryDirectory() as tmp_dir:
    try:
      mp3_path = await asyncio.to_thread(download_mp3, url, tmp_dir)
      if not os.path.exists(mp3_path):
        await status_msg.edit_text("Не удалось получить MP3-файл.")
        return

      size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
      if size_mb > 50:
        await status_msg.edit_text(
            f"Файл получился {size_mb:.1f} МБ — это больше лимита Telegram (50 МБ)."
        )
        return

      audio_file = FSInputFile(mp3_path)
      await callback.message.answer_audio(
          audio=audio_file, caption="Готово ✅"
      )
      await status_msg.delete()
    except Exception as e:
      await status_msg.edit_text(f"Не удалось скачать: {e}")


# Заглушка веб-сервера, чтобы Render видел открытый порт и не выключал контейнер
async def healthcheck(request):
  return web.Response(text="Bot is running")


async def start_web_server():
  app = web.Application()
  app.router.add_get("/", healthcheck)
  runner = web.AppRunner(app)
  await runner.setup()
  port = int(os.getenv("PORT", 10000))
  site = web.TCPSite(runner, "0.0.0.0", port)
  await site.start()


async def main():
  if not TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN!")
  await start_web_server()
  bot = Bot(token=TOKEN)
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main()) 
