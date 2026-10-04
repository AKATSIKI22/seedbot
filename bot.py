import os
import logging
import base58
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from mnemonic import Mnemonic
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set in environment")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Один раз создаём генератор
MNEMO = Mnemonic("english")

# ========== Деривация адресов ==========
def mnemonic_to_solana_address(mnemonic):
    seed = Mnemonic.to_seed(mnemonic, passphrase="")
    return base58.b58encode(seed[:32]).decode()

def derive_addresses(mnemonic):
    seed = Bip39SeedGenerator(mnemonic).Generate()

    bip44_btc = Bip44.FromSeed(seed, Bip44Coins.BITCOIN)
    btc_addr = (
        bip44_btc.Purpose().Coin().Account(0)
        .Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
        .PublicKey().ToAddress()
    )

    bip44_eth = Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
    eth_addr = (
        bip44_eth.Purpose().Coin().Account(0)
        .Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
        .PublicKey().ToAddress()
    )

    try:
        bip44_trx = Bip44.FromSeed(seed, Bip44Coins.TRON)
        trx_addr = (
            bip44_trx.Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            .PublicKey().ToAddress()
        )
    except Exception:
        trx_addr = None

    return {
        "btc": btc_addr,
        "eth": eth_addr,   # + USDT ERC-20
        "bnb": eth_addr,   # + USDT BEP-20
        "trx": trx_addr,   # + USDT TRC-20
        "sol": mnemonic_to_solana_address(mnemonic),
    }

# ========== Ядро генерации ==========
def generate_one():
    phrase = MNEMO.generate(strength=128)
    return {"phrase": phrase, "addresses": derive_addresses(phrase)}

# ========== Клавиатура ==========
def main_menu():
    keyboard = [
        [KeyboardButton("✨ 1 фразу")],
        [KeyboardButton("📦 5"), KeyboardButton("📦 10"), KeyboardButton("📦 25")],
        [KeyboardButton("📦 50"), KeyboardButton("📦 100"), KeyboardButton("📦 500")],
        [KeyboardButton("📦 1000"), KeyboardButton("📦 2000")],
        [KeyboardButton("🛑 Остановить")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# ========== Батч-генерация без спама ==========
async def generate_batch(update: Update, context: ContextTypes.DEFAULT_TYPE, count: int):
    context.user_data['generating'] = True

    progress_msg = await update.message.reply_text(f"⏳ Генерирую {count} фраз...")

    results = []
    BATCH = 50
    done = 0

    while done < count and context.user_data.get('generating', True):
        chunk = min(BATCH, count - done)
        part = await asyncio.to_thread(
            lambda n=chunk: [generate_one() for _ in range(n)]
        )
        results.extend(part)
        done += chunk

        try:
            await progress_msg.edit_text(f"⏳ {done} / {count}")
        except Exception:
            pass

    context.user_data['generating'] = False

    if not results:
        await progress_msg.edit_text("🛑 Остановлено. Ничего не сгенерировано.")
        return

    # ========== Записываем всё в один файл ==========
    filename = f"seed_phrases_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        for idx, item in enumerate(results, 1):
            a = item["addresses"]
            f.write(f"{idx}. Фраза: {item['phrase']}\n")
            f.write(f"   BTC: {a['btc']}\n")
            f.write(f"   ETH / USDT ERC-20: {a['eth']}\n")
            f.write(f"   BNB / USDT BEP-20: {a['bnb']}\n")
            f.write(f"   TRX / USDT TRC-20: {a['trx']}\n")
            f.write(f"   SOL: {a['sol']}\n")
            f.write("-" * 50 + "\n")

    await progress_msg.edit_text(f"✅ Готово: {len(results)} фраз")

    with open(filename, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=filename,
            caption=f"📄 {len(results)} сид-фраз и адресов"
        )

    os.remove(filename)

# ========== Обработка сообщений ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await generate_batch(update, context, mapping[text])
    elif text == "🛑 Остановить":
        context.user_data['generating'] = False
        await update.message.reply_text("🛑 Остановлено.", reply_markup=main_menu())
    else:
        await update.message.reply_text("Нажмите на кнопку", reply_markup=main_menu())

# ========== Старт ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
