import os
import re
import logging
import asyncio
from io import BytesIO
import aiohttp
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configure logging for debugging and monitoring
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Replace with your actual Telegram Bot Token from @BotFather
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")

# Regex pattern to match Suno song URLs (e.g., https://suno.com/song/<uuid> or https://app.suno.ai/song/<uuid>)
SUNO_URL_PATTERN = re.compile(r"https?://(?:www\.|app\.)?suno\.(?:com|ai)/song/([a-zA-Z0-9-]+)")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command and welcomes the user."""
    welcome_text = (
        "🎵 **សួស្តី! ស្វាគមន៍មកកាន់ Suno Music Downloader Bot** 🎵\n\n"
        "ផ្ញើតំណភ្ជាប់ (Link) បទចម្រៀងពី Suno មកកាន់ខ្ញុំ នោះខ្ញុំនឹងទាញយកជា File MP3 ជូនអ្នកភ្លាមៗ!\n\n"
        "ឧទាហរណ៍:\n"
        "`https://suno.com/song/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /help command."""
    help_text = (
        "📌 **របៀបប្រើប្រាស់៖**\n"
        "1. ចូលទៅកាន់គេហទំព័រ Suno ហើយចុច Share លើបទចម្រៀងដែលអ្នកចង់បាន។\n"
        "2. ចម្លងតំណភ្ជាប់ (Copy Link) នោះ។\n"
        "3. ផ្ញើតំណភ្ជាប់នោះចូលមកក្នុង Chat នេះ។\n\n"
        "Bot នឹងធ្វើការទាញយក និងផ្ញើជាឯកសារសំឡេងជូនអ្នកដោយស្វ័យប្រវត្តិ។"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def fetch_suno_track_info(session: aiohttp.ClientSession, url: str, song_id: str) -> dict:
    """
    Fetches the Suno song page and extracts metadata (title, audio URL, cover image)
    using OpenGraph meta tags, with a fallback to Suno's standard CDN pattern.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    title = f"Suno_Track_{song_id[:8]}"
    audio_url = f"https://cdn1.suno.ai/{song_id}.mp3"
    image_url = None

    try:
        async with session.get(url, headers=headers, timeout=15) as response:
            if response.status == 200:
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")

                # Extract OpenGraph Title
                og_title = soup.find("meta", property="og:title")
                if og_title and og_title.get("content"):
                    raw_title = og_title["content"].strip()
                    # Clean up common suffix if present
                    title = raw_title.replace(" | Suno", "").strip()

                # Extract OpenGraph Audio URL
                og_audio = soup.find("meta", property="og:audio")
                if og_audio and og_audio.get("content"):
                    audio_url = og_audio["content"].strip()

                # Extract OpenGraph Cover Image
                og_image = soup.find("meta", property="og:image")
                if og_image and og_image.get("content"):
                    image_url = og_image["content"].strip()
    except Exception as e:
        logger.warning(f"Failed to scrape metadata for {url}, falling back to CDN URL: {e}")

    # Sanitize filename for safe file handling
    safe_filename = re.sub(r'[\\/*?:"<>|]', "", title) or f"Suno_{song_id[:8]}"

    return {
        "title": title,
        "filename": f"{safe_filename}.mp3",
        "audio_url": audio_url,
        "image_url": image_url
    }


async def download_binary(session: aiohttp.ClientSession, file_url: str) -> BytesIO | None:
    """Downloads a file into an in-memory BytesIO stream."""
    try:
        async with session.get(file_url, timeout=30) as response:
            if response.status == 200:
                data = await response.read()
                bio = BytesIO(data)
                bio.seek(0)
                return bio
            else:
                logger.error(f"HTTP {response.status} while downloading {file_url}")
                return None
    except Exception as e:
        logger.error(f"Error downloading binary from {file_url}: {e}")
        return None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes incoming text messages to find and download Suno song links."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    match = SUNO_URL_PATTERN.search(text)

    if not match:
        await update.message.reply_text(
            "⚠️ សូមផ្ញើតំណភ្ជាប់ (Link) បទចម្រៀងពី Suno ដែលត្រឹមត្រូវ។\n"
            "ឧទាហរណ៍: `https://suno.com/song/...`",
            parse_mode="Markdown"
        )
        return

    song_url = match.group(0)
    song_id = match.group(1)

    status_msg = await update.message.reply_text("⏳ កំពុងស្វែងរក និងទាញយកបទចម្រៀង សូមរង់ចាំបន្តិច...")

    try:
        async with aiohttp.ClientSession() as session:
            # 1. Extract track metadata and audio URL
            track_info = await fetch_suno_track_info(session, song_url, song_id)

            # 2. Download the MP3 audio stream into memory
            audio_stream = await download_binary(session, track_info["audio_url"])

            if not audio_stream:
                await status_msg.edit_text(
                    "❌ មិនអាចទាញយកបទចម្រៀងនេះបានទេ។ បទចម្រៀងអាចជាឯកជន (Private) ឬត្រូវបានលុប។"
                )
                return

            # 3. Optionally download thumbnail cover image
            thumb_stream = None
            if track_info["image_url"]:
                thumb_stream = await download_binary(session, track_info["image_url"])

            # 4. Send the audio file back to the user in Telegram
            audio_stream.name = track_info["filename"]
            await update.message.reply_audio(
                audio=audio_stream,
                title=track_info["title"],
                performer="Suno AI",
                thumbnail=thumb_stream,
                caption=f"🎶 **{track_info['title']}**\n🔗 [ស្តាប់នៅលើ Suno]({song_url})",
                parse_mode="Markdown"
            )

            # Remove the loading message
            await status_msg.delete()

    except Exception as e:
        logger.error(f"Unexpected error processing {song_url}: {e}")
        await status_msg.edit_text("❌ មានបញ្ហាបច្ចេកទេសកើតឡើងក្នុងពេលទាញយក។ សូមព្យាយាមម្តងទៀតនៅពេលក្រោយ។")


def main() -> None:
    """Initializes and starts the Telegram Bot."""
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("Please set your TELEGRAM_BOT_TOKEN before running the bot.")
        print("Error: Please replace 'YOUR_TELEGRAM_BOT_TOKEN_HERE' with your actual Telegram Bot Token.")
        return

    # Build the Telegram Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Register command and message handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running and polling for messages...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
