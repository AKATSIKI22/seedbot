import os
import logging
import base58
import asyncio
import threading
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

from mnemonic import Mnemonic
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes


load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set in environment")


# ==========================================================
# ЛОГИ
# ==========================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Чтобы Telegram-токен не отображался в логах
logging.getLogger("httpx").setLevel(logging.WARNING)


# ==========================================================
# HTTP-СЕРВЕР ДЛЯ RENDER
# ==========================================================

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Telegram bot is running", 200


@web_app.route("/health")
def health():
    return "OK", 200


def run_web():
    port = int(os.environ.get("PORT", 10000))

    web_app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


# ==========================================================
# ГЕНЕРАТОР
# ==========================================================

MNEMO = Mnemonic("english")


# ==========================================================
# ДЕРИВАЦИЯ АДРЕСОВ
# ==========================================================

def mnemonic_to_solana_address(mnemonic):
    seed = Mnemonic.to_seed(mnemonic, passphrase="")
    return base58.b58encode(seed[:32]).decode()


def derive_addresses(mnemonic):
    seed = Bip39SeedGenerator(mnemonic).Generate()

    # BTC
    bip44_btc = Bip44.FromSeed(seed, Bip44Coins.BITCOIN)

    btc_addr = (
        bip44_btc.Purpose()
        .Coin()
        .Account(0)
        .Change(Bip44Changes.CHAIN_EXT)
        .AddressIndex(0)
        .PublicKey()
        .ToAddress()
    )

    # ETH
    bip44_eth = Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)

    eth_addr = (
        bip44_eth.Purpose()
        .Coin()
        .Account(0)
        .Change(Bip44Changes.CHAIN_EXT)
        .AddressIndex(0)
        .PublicKey()
        .ToAddress()
    )

    # TRON
    try:

        bip44_trx = Bip44.FromSeed(seed, Bip44Coins.TRON)

        trx_addr = (
            bip44_trx.Purpose()
            .Coin()
            .Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(0)
            .PublicKey()
            .ToAddress()
        )

    except Exception as e:

        logger.error(f"TRX derivation error: {e}")
        trx_addr = None


    return {

        "btc": btc_addr,

        "eth": eth_addr,

        # BSC использует такой же формат адреса,
        # как Ethereum
        "bnb": eth_addr,

        "trx": trx_addr,

        "sol": mnemonic_to_solana_address(mnemonic),

    }


# ==========================================================
# ГЕНЕРАЦИЯ ОДНОЙ ФРАЗЫ
# ==========================================================

def generate_one():

    phrase = MNEMO.generate(strength=128)

    return {

        "phrase": phrase,

        "addresses": derive_addresses(phrase)

    }


# ==========================================================
# КЛАВИАТУРА
# ==========================================================

def main_menu():

    keyboard = [

        [
            KeyboardButton("✨ 1 фразу")
        ],

        [
            KeyboardButton("📦 5"),
            KeyboardButton("📦 10"),
            KeyboardButton("📦 25")
        ],

        [
            KeyboardButton("📦 50"),
            KeyboardButton("📦 100"),
            KeyboardButton("📦 500")
        ],

        [
            KeyboardButton("📦 1000"),
            KeyboardButton("📦 2000")
        ],

        [
            KeyboardButton("🛑 Остановить")
        ]

    ]

    return ReplyKeyboardMarkup(

        keyboard,

        resize_keyboard=True,

        one_time_keyboard=False

    )


# ==========================================================
# БАТЧ-ГЕНЕРАЦИЯ
# ==========================================================

async def generate_batch(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    count: int
):

    context.user_data["generating"] = True

    progress_msg = await update.message.reply_text(
        f"⏳ Генерирую {count} фраз..."
    )


    results = []

    BATCH = 50

    done = 0


    while (
        done < count
        and context.user_data.get("generating", True)
    ):

        chunk = min(
            BATCH,
            count - done
        )


        part = await asyncio.to_thread(

            lambda n=chunk: [

                generate_one()

                for _ in range(n)

            ]

        )


        results.extend(part)

        done += chunk


        try:

            await progress_msg.edit_text(
                f"⏳ {done} / {count}"
            )

        except Exception:

            pass


    context.user_data["generating"] = False


    if not results:

        await progress_msg.edit_text(
            "🛑 Остановлено. Ничего не сгенерировано."
        )

        return


    # ======================================================
    # СОЗДАЁМ TXT-ФАЙЛ
    # ======================================================

    filename = (

        f"seed_phrases_"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    )


    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:

        for idx, item in enumerate(
            results,
            1
        ):

            a = item["addresses"]


            f.write(
                f"{idx}. Фраза: "
                f"{item['phrase']}\n"
            )


            f.write(
                f"   BTC: "
                f"{a['btc']}\n"
            )


            f.write(
                f"   ETH / USDT ERC-20: "
                f"{a['eth']}\n"
            )


            f.write(
                f"   BNB / USDT BEP-20: "
                f"{a['bnb']}\n"
            )


            f.write(
                f"   TRX / USDT TRC-20: "
                f"{a['trx']}\n"
            )


            f.write(
                f"   SOL: "
                f"{a['sol']}\n"
            )


            f.write(
                "-" * 50
                + "\n"
            )


    await progress_msg.edit_text(
        f"✅ Готово: {len(results)} фраз"
    )


    with open(
        filename,
        "rb"
    ) as f:

        await update.message.reply_document(

            document=f,

            filename=filename,

            caption=(
                f"📄 {len(results)} "
                f"сид-фраз и адресов"
            )

        )


    try:

        os.remove(filename)

    except Exception as e:

        logger.error(
            f"File remove error: {e}"
        )


# ==========================================================
# ОБРАБОТКА СООБЩЕНИЙ
# ==========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text


    mapping = {

        "✨ 1 фразу": 1,

        "📦 5": 5,

        "📦 10": 10,

        "📦 25": 25,

        "📦 50": 50,

        "📦 100": 100,

        "📦 500": 500,

        "📦 1000": 1000,

        "📦 2000": 2000,

    }


    if text in mapping:

        await generate_batch(
            update,
            context,
            mapping[text]
        )


    elif text == "🛑 Остановить":

        context.user_data["generating"] = False

        await update.message.reply_text(

            "🛑 Остановлено.",

            reply_markup=main_menu()

        )


    else:

        await update.message.reply_text(

            "Нажмите на кнопку",

            reply_markup=main_menu()

        )


# ==========================================================
# /START
# ==========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "🚀 Seed Phrase Generator\n\n"

        "Генерирует сид-фразы и адреса:\n"

        "• BTC\n"

        "• ETH / USDT ERC-20\n"

        "• BNB / USDT BEP-20\n"

        "• TRX / USDT TRC-20\n"

        "• SOL\n\n"

        "Результат приходит одним файлом.\n\n"

        "⬇️ Нажмите кнопку:",

        reply_markup=main_menu()

    )


# ==========================================================
# ЗАПУСК
# ==========================================================

def main():

    # Запускаем HTTP-сервер для Render
    web_thread = threading.Thread(
        target=run_web,
        daemon=True
    )

    web_thread.start()


    logger.info(
        "HTTP server started"
    )


    # Запускаем Telegram-бота
    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )


    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    app.add_handler(
        MessageHandler(

            filters.TEXT
            & ~filters.COMMAND,

            handle_message

        )
    )


    logger.info(
        "Telegram bot started"
    )


    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
