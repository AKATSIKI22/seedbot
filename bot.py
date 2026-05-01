import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from mnemonic import Mnemonic
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
import requests
from web3 import Web3
import json

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set in environment")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

ETH_RPC = "https://cloudflare-eth.com"
BSC_RPC = "https://bsc-dataseed.binance.org/"
w3_eth = Web3(Web3.HTTPProvider(ETH_RPC))
w3_bsc = Web3(Web3.HTTPProvider(BSC_RPC))

USDT_ERC20 = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
USDT_BEP20 = "0x55d398326f99059fF775485246999027B3197955"
ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]')

def get_eth_balance(address):
    try:
        balance_wei = w3_eth.eth.get_balance(address)
        return w3_eth.from_wei(balance_wei, 'ether')
    except:
        return None

def get_usdt_erc20_balance(address):
    try:
        contract = w3_eth.eth.contract(address=Web3.to_checksum_address(USDT_ERC20), abi=ERC20_ABI)
        balance = contract.functions.balanceOf(address).call()
        return balance / 10**6
    except:
        return None

def get_bnb_balance(address):
    try:
        balance_wei = w3_bsc.eth.get_balance(address)
        return w3_bsc.from_wei(balance_wei, 'ether')
    except:
        return None

def get_usdt_bep20_balance(address):
    try:
        contract = w3_bsc.eth.contract(address=Web3.to_checksum_address(USDT_BEP20), abi=ERC20_ABI)
        balance = contract.functions.balanceOf(address).call()
        return balance / 10**18
    except:
        return None

def get_btc_balance(address):
    url = f"https://api.blockchair.com/bitcoin/dashboards/address/{address}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        balance_sat = data['data'][address]['address']['balance']
        return balance_sat / 1e8
    except:
        return None

def derive_addresses_from_mnemonic(mnemonic):
    seed = Bip39SeedGenerator(mnemonic).Generate()
    bip44_btc = Bip44.FromSeed(seed, Bip44Coins.BITCOIN)
    btc_addr = bip44_btc.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    bip44_eth = Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
    eth_addr = bip44_eth.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    return {"btc": btc_addr, "eth": eth_addr, "bnb": eth_addr}

def check_all_balances(mnemonic):
    try:
        addrs = derive_addresses_from_mnemonic(mnemonic)
        btc_bal = get_btc_balance(addrs["btc"])
        eth_bal = get_eth_balance(addrs["eth"])
        usdt_erc20 = get_usdt_erc20_balance(addrs["eth"])
        bnb_bal = get_bnb_balance(addrs["bnb"])
        usdt_bep20 = get_usdt_bep20_balance(addrs["bnb"])
        return {
            "btc": btc_bal if btc_bal is not None else 0,
            "eth": eth_bal if eth_bal is not None else 0,
            "usdt_erc20": usdt_erc20 if usdt_erc20 is not None else 0,
            "bnb": bnb_bal if bnb_bal is not None else 0,
            "usdt_bep20": usdt_bep20 if usdt_bep20 is not None else 0,
            "addresses": addrs
        }
    except Exception as e:
        logger.error(f"Balance check error: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот для генерации и проверки BIP39 сид-фраз.\n"
                                    "Команды:\n"
                                    "/generate - сгенерировать новую сид-фразу и проверить балансы\n"
                                    "/check <сид-фраза> - проверить балансы для указанной фразы\n"
                                    "/stats - статистика проверок")

cache = {}

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Генерирую новую сид-фразу и проверяю балансы...")
    mnemo = Mnemonic("english")
    mnemonic = mnemo.generate(strength=128)
    result = check_all_balances(mnemonic)
    if not result:
        await msg.edit_text("Ошибка при проверке балансов. Попробуйте позже.")
        return
    text = f"<b>Сид-фраза:</b>\n<code>{mnemonic}</code>\n\n"
    text += f"<b>Балансы:</b>\n"
    text += f"₿ BTC: {result['btc']:.8f}\n"
    text += f"Ξ ETH: {result['eth']:.6f}\n"
    text += f"💲 USDT (ERC20): {result['usdt_erc20']:.2f}\n"
    text += f"🔶 BNB: {result['bnb']:.6f}\n"
    text += f"💲 USDT (BEP20): {result['usdt_bep20']:.2f}\n\n"
    text += f"<b>Адреса:</b>\nBTC: <code>{result['addresses']['btc']}</code>\nETH: <code>{result['addresses']['eth']}</code>\nBNB: <code>{result['addresses']['bnb']}</code>"
    await msg.edit_text(text, parse_mode="HTML")
    cache[mnemonic] = result

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите сид-фразу после команды /check")
        return
    mnemonic = " ".join(context.args).strip()
    if len(mnemonic.split()) not in (12, 15, 18, 21, 24):
        await update.message.reply_text("Сид-фраза должна содержать 12, 15, 18, 21 или 24 слова.")
        return
    msg = await update.message.reply_text("Проверяю балансы...")
    if mnemonic in cache:
        result = cache[mnemonic]
    else:
        result = check_all_balances(mnemonic)
        if result:
            cache[mnemonic] = result
    if not result:
        await msg.edit_text("Ошибка при проверке. Возможно, неверная фраза или проблемы с соединением.")
        return
    text = f"<b>Сид-фраза:</b>\n<code>{mnemonic}</code>\n\n"
    text += f"<b>Балансы:</b>\n"
    text += f"₿ BTC: {result['btc']:.8f}\n"
    text += f"Ξ ETH: {result['eth']:.6f}\n"
    text += f"💲 USDT (ERC20): {result['usdt_erc20']:.2f}\n"
    text += f"🔶 BNB: {result['bnb']:.6f}\n"
    text += f"💲 USDT (BEP20): {result['usdt_bep20']:.2f}\n\n"
    text += f"<b>Адреса:</b>\nBTC: <code>{result['addresses']['btc']}</code>\nETH: <code>{result['addresses']['eth']}</code>\nBNB: <code>{result['addresses']['bnb']}</code>"
    await msg.edit_text(text, parse_mode="HTML")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = len(cache)
    non_empty = 0
    for res in cache.values():
        if res['btc'] > 0 or res['eth'] > 0 or res['usdt_erc20'] > 0 or res['bnb'] > 0 or res['usdt_bep20'] > 0:
            non_empty += 1
    await update.message.reply_text(f"Статистика кэша:\nВсего проверено фраз: {total}\nИз них с ненулевым балансом: {non_empty}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    words = text.split()
    if len(words) in (12, 15, 18, 21, 24):
        await update.message.reply_text("Похоже на сид-фразу. Используйте /check " + text + " для проверки балансов.")
    else:
        await update.message.reply_text("Используйте команды /generate, /check или /stats")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    try:
        from keep_alive import keep_alive
        keep_alive()
    except ImportError:
        pass
    app.run_polling()

if __name__ == "__main__":
    main()
