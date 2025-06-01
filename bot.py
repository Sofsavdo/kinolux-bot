import os
import psycopg2
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, ConversationHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import random
import logging

# Logging sozlamalari
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Sozlamalar
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 6878669336))
CHANNELS = ["@Uzum_market_yandex"]
MOVIE_CHANNEL = os.getenv("MOVIE_CHANNEL", "@Kino_luxTV")
PROMO_CHANNEL = os.getenv("PROMO_CHANNEL", "@Promokodlar_bonus")
TRAILER_CHANNEL = os.getenv("TRAILER_CHANNEL", "@kinoluxTreler")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 80))

# ConversationHandler holatlari
AWAITING_VIDEO, AWAITING_DETAILS = range(2)

# PostgreSQL bilan ulanish
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        raise

# Jadval yaratish (agar mavjud bo‘lmasa)
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS last_code (
            id SERIAL PRIMARY KEY,
            code INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS message_ids (
            id SERIAL PRIMARY KEY,
            code TEXT NOT NULL,
            message_id TEXT NOT NULL
        );
    """)
    # Agar last_code jadvalida hech qanday yozuv bo‘lmasa, boshlang‘ich qiymat qo‘shish
    cursor.execute("SELECT COUNT(*) FROM last_code")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO last_code (code) VALUES (100)")
    conn.commit()
    cursor.close()
    conn.close()

# Oxirgi ishlatilgan kodni olish
def get_last_code():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT code FROM last_code ORDER BY id DESC LIMIT 1")
        last_code = cursor.fetchone()[0]
        logger.info(f"Last code read: {last_code}")
        return last_code
    except Exception as e:
        logger.error(f"Error reading last code: {e}")
        return 100
    finally:
        cursor.close()
        conn.close()

# Yangi kod generatsiya qilish
def generate_code():
    last_code = get_last_code()
    new_code = last_code + 1
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO last_code (code) VALUES (%s)", (new_code,))
        conn.commit()
        logger.info(f"New code generated: {new_code}")
        return str(new_code)
    except Exception as e:
        logger.error(f"Error writing new code: {e}")
        return str(new_code)
    finally:
        cursor.close()
        conn.close()

# Xabar ID larini saqlash
def save_message_id(code, message_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO message_ids (code, message_id) VALUES (%s, %s)", (code, message_id))
        conn.commit()
        logger.info(f"Saved message ID for code {code}: {message_id}")
    except Exception as e:
        logger.error(f"Error saving message ID for code {code}: {e}")
    finally:
        cursor.close()
        conn.close()

def get_message_id(code):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT message_id FROM message_ids WHERE code = %s", (code,))
        result = cursor.fetchone()
        if result:
            logger.info(f"Found message ID for code {code}: {result[0]}")
            return result[0]
        logger.warning(f"No message ID found for code {code}")
        return None
    except Exception as e:
        logger.error(f"Error reading message ID: {e}")
        return None
    finally:
        cursor.close()
        conn.close()

# Obuna tekshiruvi
def get_subscription_keyboard():
    keyboard = [
        [InlineKeyboardButton("Kanalga a'zo bo'ling", url="https://t.me/Uzum_market_yandex")],
        [InlineKeyboardButton("A'zolikni tekshirish", callback_data="check_subscription")]
    ]
    return InlineKeyboardMarkup(keyboard)

def check_subscription(context, user_id):
    for channel in CHANNELS:
        try:
            member = context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            logger.error(f"Error checking subscription for {channel}: {e}")
            return False
    return True

# Start buyrug‘i
def start(update, context):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    args = context.args
    if args:
        code = args[0]
        if check_subscription(context, user_id):
            handle_code_logic(update, context, code)
        else:
            update.message.reply_text(
                "Botdan foydalanish uchun quyidagi kanalga a'zo bo'ling:",
                reply_markup=get_subscription_keyboard()
            )
            context.user_data["pending_code"] = code
    else:
        if check_subscription(context, user_id):
            update.message.reply_text(f"Assalomu alaykum, {user_name}! Kino kodini yuboring.")
        else:
            update.message.reply_text(
                "Botdan foydalanish uchun quyidagi kanalga a'zo bo'ling:",
                reply_markup=get_subscription_keyboard()
            )

# Obuna tekshirish tugmasi
def check_subscription_button(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.first_name
    if check_subscription(context, user_id):
        query.message.edit_text(f"Assalomu alaykum, {user_name}! Kino kodini yuboring.")
        if "pending_code" in context.user_data:
            handle_code_logic(query.message, context, context.user_data.pop("pending_code"))
    else:
        query.message.edit_text("Iltimos, kanalga a'zo bo'ling:", reply_markup=get_subscription_keyboard())

# Kino qo‘shish (Admin)
def add_movie(update, context):
    if update.message.from_user.id != ADMIN_ID:
        update.message.reply_text("Sizda bu amalni bajarish huquqi yo'q.")
        return ConversationHandler.END
    update.message.reply_text("Iltimos, kino faylini (MP4 yoki boshqa video) yuboring.")
    return AWAITING_VIDEO

def handle_video(update, context):
    if update.message.video:
        video = update.message.video.file_id
        context.user_data["video"] = video
        update.message.reply_text(
            "Video qabul qilindi. Iltimos, kino ma'lumotlarini yuboring:\n"
            "Format: Kanal nomi, Kino nomi, Janr, Online ko'rish havolasi\n"
            "Misol: @Kino_luxTV, TestKino, Drama, https://example.com"
        )
        return AWAITING_DETAILS
    else:
        update.message.reply_text("Iltimos, video fayl yuboring.")
        return AWAITING_VIDEO

def handle_details(update, context):
    try:
        details = update.message.text.split(",")
        if len(details) != 4:
            update.message.reply_text("Noto‘g‘ri format. Iltimos, quyidagi formatda yuboring:\n"
                                      "Kanal nomi, Kino nomi, Janr, Online ko'rish havolasi")
            return AWAITING_DETAILS
        channel_name, title, genre, link = [d.strip() for d in details]
        video = context.user_data.pop("video", None)
        if not video:
            update.message.reply_text("Video fayl topilmadi. Qaytadan boshlang.")
            return ConversationHandler.END
        # Avtomatik kod generatsiya
        code = generate_code()
        try:
            # Kino faylini kanalga yuborish
            message = context.bot.send_video(
                chat_id=MOVIE_CHANNEL,
                video=video,
                caption=f"Kod: {code}\nKanal: {channel_name}\nKino: {title}\nJanr: {genre}\nHavola: {link}"
            )
            update.message.reply_text(f"Kino muvaffaqiyatli qo'shildi! Kod: {code}, Xabar ID: {message.message_id}")
            save_message_id(code, message.message_id)
            return ConversationHandler.END
        except Exception as e:
            update.message.reply_text(f"Kino qo'shishda xato: {e}")
            logger.error(f"Error posting to {MOVIE_CHANNEL}: {e}")
            return ConversationHandler.END
    except Exception as e:
        update.message.reply_text(f"Ma'lumotlarda xato: {e}")
        return AWAITING_DETAILS

def cancel(update, context):
    update.message.reply_text("Kino qo'shish bekor qilindi.")
    context.user_data.clear()
    return ConversationHandler.END

# Kino kodi so‘rovi
def handle_code_logic(update, context, code):
    user_id = update.message.from_user.id
    message_id = get_message_id(code)
    if message_id:
        try:
            message_id = int(message_id)
            logger.info(f"Attempting to forward message ID {message_id} from {MOVIE_CHANNEL}")
            sent_message = context.bot.forward_message(
                chat_id=user_id,
                from_chat_id=MOVIE_CHANNEL,
                message_id=message_id
            )
            # Tugmalar qo‘shish
            keyboard = [
                [InlineKeyboardButton("Barcha sifatli kinolar", url=f"https://t.me/{TRAILER_CHANNEL[1:]}")]
            ]
            context.bot.send_message(
                chat_id=user_id,
                text="Siz uchun yanada qiziq kinolar ⬇️",
                reply_to_message_id=sent_message.message_id,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            if "promo_sent" not in context.user_data:
                promo_message_id = get_random_promo(context)
                if promo_message_id:
                    update.message.reply_text("Tabriklaymiz, siz promo kod yutib oldingiz! 🎉")
                    promo_message = context.bot.forward_message(
                        chat_id=user_id,
                        from_chat_id=PROMO_CHANNEL,
                        message_id=promo_message_id
                    )
                    # Promo kod tagida tugma
                    keyboard = [
                        [InlineKeyboardButton("Barcha promo kodlaringiz", url=f"https://t.me/{PROMO_CHANNEL[1:]}")]
                    ]
                    context.bot.send_message(
                        chat_id=user_id,
                        text="Barcha promo kodlarni ko‘rish uchun:",
                        reply_to_message_id=promo_message.message_id,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    context.user_data["promo_sent"] = True
                else:
                    update.message.reply_text("Promo kod topilmadi, keyinroq urinib ko‘ring.")
        except ValueError:
            update.message.reply_text("Xato: Kodga mos xabar ID noto‘g‘ri formatda.")
            logger.error(f"Invalid message ID format for code {code}: {message_id}")
        except Exception as e:
            update.message.reply_text(f"Kechirasiz, xato yuz berdi: {e}")
            logger.error(f"Error forwarding message for code {code}: {e}")
    else:
        keyboard = [
            [InlineKeyboardButton("Barcha kino kodlari ⬇️", url=f"https://t.me/{TRAILER_CHANNEL[1:]}")]
        ]
        update.message.reply_text(
            "Kechirasiz, kod noto‘g‘ri 😔",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        logger.warning(f"Code {code} not found in message_ids")

def handle_code(update, context):
    user_id = update.message.from_user.id
    if not check_subscription(context, user_id):
        update.message.reply_text(
            "Iltimos, kanalga a'zo bo'ling:",
            reply_markup=get_subscription_keyboard()
        )
        return
    code = update.message.text
    handle_code_logic(update, context, code)

# Tasodifiy promo kod xabar ID sini olish
def get_random_promo(context):
    try:
        message_ids = []
        for i in range(1, 50):
            try:
                message = context.bot.forward_message(
                    chat_id=ADMIN_ID,
                    from_chat_id=PROMO_CHANNEL,
                    message_id=i
                )
                if message.photo:
                    message_ids.append(i)
                context.bot.delete_message(chat_id=ADMIN_ID, message_id=message.message_id)
            except:
                continue
        if message_ids:
            return random.choice(message_ids)
        return None
    except Exception as e:
        logger.error(f"Promo kod olishda xato: {e}")
        return None

# Barcha promo kodlar
def promocodes(update, context):
    keyboard = [
        [InlineKeyboardButton("Barcha promo kodlar", url="https://t.me/Promokodlar_bonus")]
    ]
    update.message.reply_text(
        "Quyidagi kanalda barcha promo kodlarni ko‘rishingiz mumkin:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Webhook uchun handler
def webhook(update, context):
    if update.message:
        if update.message.text == "/start":
            start(update, context)
        elif update.message.text == "/promocodes":
            promocodes(update, context)
        else:
            handle_code(update, context)
    elif update.callback_query:
        check_subscription_button(update, context)

# Asosiy funksiya
def main():
    if not TOKEN:
        logger.error("TOKEN environment variable not set")
        raise ValueError("TOKEN environment variable not set")
    if not DATABASE_URL:
        logger.error("DATABASE_URL environment variable not set")
        raise ValueError("DATABASE_URL environment variable not set")
    # Database’ni ishga tushirish
    init_db()
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    # ConversationHandler for add_movie
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("addmovie", add_movie)],
        states={
            AWAITING_VIDEO: [MessageHandler(Filters.video, handle_video)],
            AWAITING_DETAILS: [MessageHandler(Filters.text & ~Filters.command, handle_details)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    dp.add_handler(conv_handler)
    dp.add_handler(MessageHandler(Filters.all, webhook))
    dp.add_handler(CallbackQueryHandler(webhook))
    # Webhook rejimida ishga tushirish
    updater.start_webhook(listen="0.0.0.0", port=PORT, url_path="webhook")
    updater.bot.set_webhook(f"https://kinolux-bot.onrender.com/webhook")
    updater.idle()

if __name__ == "__main__":
    main()