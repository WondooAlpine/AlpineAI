import os
import glob
import asyncio
import random
import traceback
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from generate_itinerary import (
    generate_itinerary_content,
    render_itinerary_pages,
    TourItinerary,
)

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = "8919352959:AAHqN60Au-cSUl5tAoWfW-klkIFWmE598oo"

GREETING_WORDS = {
    "hello", "hi", "hey", "hola", "namaste", "good morning",
    "good afternoon", "good evening", "yo", "start"
}

TRAVEL_TIDBITS = [
    "🏔️ *Did you know?* Kangchenjunga means 'The Five Treasures of Snows' in Tibetan.",
    "🚗 *Travel Tip:* The drive along the Teesta River offers some of the finest mountain valley views in the East.",
    "☕ *Foodie Note:* Fresh piping hot momos taste best with local fermented Dalle Khursani chili sauce!",
    "🌲 *Did you know?* Kaluk and Rinchenpong offer virtually 180° uninterrupted panoramic views of the Himalayan range.",
    "🏡 *Culture Tip:* Traditional Lepcha and Bhutia homestays welcome guests with homebrewed warm millet beverage.",
    "📸 *Photo Tip:* Golden hour at mountain monasteries yields magical soft light against prayer flags."
]

# ---------------------------------------------------------------------------
# ENGAGING LIVE PROGRESS & SPINNER
# ---------------------------------------------------------------------------
def make_progress_bar(percent: int, bar_length: int = 10) -> str:
    filled_length = int(round(bar_length * percent / 100))
    bar = "█" * filled_length + "░" * (bar_length - filled_length)
    return f"`[{bar}]` *{percent}%*"


class EngagingProgressMonitor:
    """Animates a dynamic progress card with rotating travel facts and spinners."""
    def __init__(self, message, initial_stage: str, initial_percent: int = 15):
        self.message = message
        self.stage = initial_stage
        self.percent = initial_percent
        self.is_running = True
        self._task = None
        self.tidbits = random.sample(TRAVEL_TIDBITS, len(TRAVEL_TIDBITS))
        self.tidbit_index = 0

    async def _animate(self):
        spinners = ["🧭 Exploring routes...", "✈️ Charting journeys...", "🏔️ Scanning peaks...", "🚗 Mapping valleys...", "📸 Framing views..."]
        step = 0
        while self.is_running:
            spinner_icon = spinners[step % len(spinners)]
            tidbit = self.tidbits[self.tidbit_index % len(self.tidbits)]
            
            # Subtly increment percent for a natural live-loading feel
            if self.percent < 90:
                self.percent = min(self.percent + 2, 90)

            bar = make_progress_bar(self.percent)
            text = (
                f"{spinner_icon}\n\n"
                f"{bar}\n"
                f"📍 *Stage:* _{self.stage}_\n\n"
                f"💡 {tidbit}\n\n"
                f"_Curating your custom flyers..._"
            )
            try:
                await self.message.edit_text(text, parse_mode="Markdown")
            except Exception:
                pass

            step += 1
            if step % 2 == 0:
                self.tidbit_index += 1

            await asyncio.sleep(3.2)

    def set_stage(self, new_stage: str, new_percent: int):
        self.stage = new_stage
        self.percent = new_percent

    async def start(self):
        self._task = asyncio.create_task(self._animate())

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()


class ChatActionHeartbeat:
    """Keeps the Telegram status bar ('typing...' or 'uploading...') active."""
    def __init__(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, action=ChatAction.TYPING):
        self.context = context
        self.chat_id = chat_id
        self.action = action
        self._task = None

    async def _loop(self):
        while True:
            try:
                await self.context.bot.send_chat_action(chat_id=self.chat_id, action=self.action)
            except Exception:
                pass
            await asyncio.sleep(4)

    def __enter__(self):
        self._task = asyncio.create_task(self._loop())
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._task:
            self._task.cancel()


# ---------------------------------------------------------------------------
# MESSAGE FORMATTERS
# ---------------------------------------------------------------------------
def format_itinerary_preview(data: TourItinerary) -> str:
    lines = [
        f"🗺️ *{data.tour_title.upper()}*",
        f"⏱️ *Duration:* {data.duration}\n",
        "─────────────────────────\n"
    ]
    for day in data.days:
        lines.append(f"📍 *Day {day.day_number}: {day.route_title}*")
        lines.append(f"🏷️ *Key Attraction:* {day.place_name}")
        for bullet in day.bullets:
            lines.append(f"  {bullet}")
        lines.append("")

    lines.append("─────────────────────────")
    lines.append("Would you like to generate the flyers and PDF, or make any changes to the routes?")
    return "\n".join(lines)


async def send_chunked_preview(update: Update, full_text: str, reply_markup=None):
    MAX_CHUNK_SIZE = 3500
    if len(full_text) <= MAX_CHUNK_SIZE:
        await update.message.reply_text(full_text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    lines = full_text.split("\n")
    chunks = []
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 > MAX_CHUNK_SIZE:
            chunks.append(current_chunk.strip())
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    for chunk in chunks[:-1]:
        await update.message.reply_text(chunk, parse_mode="Markdown")

    await update.message.reply_text(chunks[-1], reply_markup=reply_markup, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# BOT HANDLERS
# ---------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name or "traveler"
    welcome_text = (
        f"👋 Hello *{user_name}*! Welcome to *Wondoo Itinerary Generator*.\n\n"
        "Tell me what tour you would like to plan (e.g. `Kaluk & Rinchenpong 3N/4D` or `Darjeeling 4N/5D`).\n\n"
        "I'll first show you the text plan so you can review or adjust routes before creating the PDF!"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name or "traveler"
    chat_id = update.effective_chat.id
    incoming_text = update.message.text.strip()

    if not incoming_text or incoming_text.startswith("/"):
        return

    cleaned_text = incoming_text.lower().strip("!.,? ")
    if cleaned_text in GREETING_WORDS:
        greeting_reply = (
            f"👋 Hello *{user_name}*!\n\n"
            "Tell me about the tour you'd like to plan:\n"
            "• Destination (e.g. Kaluk, Pelling, Darjeeling)\n"
            "• Duration (e.g. 3N/4D or 4N/5D)\n\n"
            "Send the details below to start!"
        )
        await update.message.reply_text(greeting_reply, parse_mode="Markdown")
        return

    is_editing = context.user_data.get("awaiting_edit", False)
    current_plan = context.user_data.get("current_itinerary")

    if is_editing and current_plan:
        prompt_to_send = (
            f"Update this itinerary:\n"
            f"Title: {current_plan.tour_title}\n"
            f"Current Days: {[d.model_dump() for d in current_plan.days]}\n\n"
            f"Requested Modification: {incoming_text}"
        )
        initial_label = "Modifying routes & adjusting day plan..."
    else:
        prompt_to_send = incoming_text
        initial_label = "Drafting day-by-day itinerary with Gemini..."

    status_msg = await update.message.reply_text(
        f"🧭 *Mapping your adventure...*\n\n{make_progress_bar(20)}\n📍 _{initial_label}_",
        parse_mode="Markdown"
    )

    monitor = EngagingProgressMonitor(status_msg, initial_stage=initial_label, initial_percent=20)
    await monitor.start()

    try:
        with ChatActionHeartbeat(context, chat_id, ChatAction.TYPING):
            itinerary_data = await asyncio.to_thread(generate_itinerary_content, prompt_to_send)

        monitor.set_stage("Formatting your preview cards...", 95)
        await asyncio.sleep(0.5)
        await monitor.stop()

        context.user_data["current_itinerary"] = itinerary_data
        context.user_data["awaiting_edit"] = False

        preview_text = format_itinerary_preview(itinerary_data)

        keyboard = [
            [InlineKeyboardButton("✅ Looks Great! Generate Flyers & PDF", callback_data="confirm_export")],
            [InlineKeyboardButton("✏️ Request Changes / Edit Route", callback_data="request_edit")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await status_msg.delete()
        except Exception:
            pass

        await send_chunked_preview(update, preview_text, reply_markup=reply_markup)

    except Exception as e:
        await monitor.stop()
        traceback.print_exc()
        err_msg = str(e).replace("`", "")[:250]
        try:
            await status_msg.edit_text(f"❌ Error: {err_msg}")
        except Exception:
            await update.message.reply_text(f"❌ Error: {err_msg}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    itinerary_data = context.user_data.get("current_itinerary")
    if not itinerary_data:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⚠️ Session expired. Please send a new tour prompt.")
        return

    if query.data == "request_edit":
        context.user_data["awaiting_edit"] = True
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "✏️ *What changes would you like to make?*\n\n"
            "Example: `Change Day 2 route to Pelling and add Skywalk`\n\n"
            "Type your instructions below:",
            parse_mode="Markdown"
        )
        return

    if query.data == "confirm_export":
        await query.edit_message_reply_markup(reply_markup=None)
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        progress_msg = await query.message.reply_text(
            f"🎨 *Assembling your brochure...*\n\n{make_progress_bar(15)}\n📍 _Initializing renderer & fetching photos..._",
            parse_mode="Markdown"
        )

        monitor = EngagingProgressMonitor(progress_msg, initial_stage="Fetching authentic landmark photos...", initial_percent=20)
        await monitor.start()

        session_id = f"job_{user_id}_{int(asyncio.get_event_loop().time())}"
        job_output_dir = os.path.join("telegram_output", session_id)
        os.makedirs(job_output_dir, exist_ok=True)

        try:
            with ChatActionHeartbeat(context, chat_id, ChatAction.UPLOAD_PHOTO):
                monitor.set_stage("Rendering branded daily flyers...", 45)
                
                # Render flyers and PDF
                await render_itinerary_pages(
                    itinerary=itinerary_data,
                    template_path="template_bg.png",
                    output_dir=job_output_dir,
                )

                monitor.set_stage("Compiling PDF & preparing uploads...", 85)
                await asyncio.sleep(0.6)
                await monitor.stop()

                # Send day flyers
                day_images = sorted(glob.glob(os.path.join(job_output_dir, "Day_*.jpg")))
                for img_path in day_images:
                    file_name = os.path.basename(img_path)
                    day_label = file_name.replace(".jpg", "").replace("_", " ")
                    with open(img_path, "rb") as photo:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=photo,
                            caption=f"📍 {itinerary_data.tour_title} - {day_label}",
                        )

                # Send sightseeing summary page
                sightseeing_path = os.path.join(job_output_dir, "Sightseeing_Enroute.jpg")
                if os.path.exists(sightseeing_path):
                    with open(sightseeing_path, "rb") as photo:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=photo,
                            caption="🗺️ Sightseeing Enroute Summary",
                        )

                # Send compiled PDF
                pdf_files = glob.glob(os.path.join(job_output_dir, "*.pdf"))
                if pdf_files:
                    with open(pdf_files[0], "rb") as pdf_doc:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=pdf_doc,
                            caption=f"📕 Complete Itinerary PDF: {itinerary_data.tour_title}",
                        )

            await progress_msg.edit_text("🎉 *All done! Your branded flyers and merged PDF are ready.*", parse_mode="Markdown")

        except Exception as e:
            await monitor.stop()
            traceback.print_exc()
            err_msg = str(e).replace("`", "")[:250]
            try:
                await progress_msg.edit_text(f"❌ Failed during rendering: {err_msg}")
            except Exception:
                await query.message.reply_text(f"❌ Failed during rendering: {err_msg}")


# ---------------------------------------------------------------------------
# MAIN BOT RUNNER
# ---------------------------------------------------------------------------
def main():
    print("🤖 Starting Wondoo Interactive Telegram Bot with Engaging Progress...")
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Bot is running! Try asking for an itinerary.")
    app.run_polling()


if __name__ == "__main__":
    main()