# bot_telegram.py
import os
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from ai_engine import chat_with_ai
from order_manager import (
    get_or_create_order, reset_order, ItemPesanan,
    orders, get_user_mode, set_user_mode, user_modes
)
from handoff_manager import format_handoff_notify_admin
from invoice_generator import generate_invoice
from gmail_watcher import start_gmail_watcher_thread
from menu import REKENING
from sheets_sync import upsert_order_to_sheet, mark_order_paid

load_dotenv()
logging.basicConfig(level=logging.INFO)

ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")

bot_app = None
bot_loop = None
conversation_histories = {}
pending_payments = {}


def is_admin(user_id: str) -> bool:
    return str(user_id) == str(ADMIN_CHAT_ID)


def _hard_reset_user(user_id: str, context=None):
    reset_order(user_id)
    conversation_histories.pop(user_id, None)

    keys_to_delete = [k for k, v in pending_payments.items() if v == user_id]
    for k in keys_to_delete:
        pending_payments.pop(k, None)

    set_user_mode(user_id, "bot")

    jq = None
    if context and context.job_queue:
        jq = context.job_queue
    elif bot_app and bot_app.job_queue:
        jq = bot_app.job_queue

    if jq:
        jobs = jq.get_jobs_by_name(f"timeout_{user_id}")
        for job in jobs:
            job.schedule_removal()

    print(f"🗑️  Sesi user {user_id} di-reset sepenuhnya.")


def _normalize_item_fields(item_data: dict):
    nama = (item_data.get("nama") or "").strip()
    jumlah = int(item_data.get("jumlah") or 0)
    harga = int(item_data.get("harga") or 0)
    tanggal = (item_data.get("tanggal") or "").strip()
    return nama, jumlah, harga, tanggal


def _find_matching_item(order, nama: str, tanggal: str):
    if not nama:
        return None

    nama_lower = nama.lower()

    exact_match = next(
        (i for i in order.items if i.nama.lower() == nama_lower and (i.tanggal_antar or "").strip() == tanggal),
        None
    )
    if exact_match:
        return exact_match

    flexible_match = next(
        (
            i for i in order.items
            if i.nama.lower() == nama_lower and (
                not (i.tanggal_antar or "").strip() or not tanggal
            )
        ),
        None
    )
    if flexible_match:
        return flexible_match

    if len(order.items) == 1 and order.items[0].nama.lower() == nama_lower:
        return order.items[0]

    return None


def _upsert_order_item(order, item_data: dict):
    nama, jumlah, harga, tanggal = _normalize_item_fields(item_data)
    if not (nama and jumlah and harga):
        return False

    existing_item = _find_matching_item(order, nama, tanggal)

    if existing_item:
        existing_item.jumlah = jumlah
        existing_item.harga_satuan = harga
        if tanggal:
            existing_item.tanggal_antar = tanggal
        return True

    order.items.append(ItemPesanan(
        nama=nama,
        jumlah=jumlah,
        harga_satuan=harga,
        tanggal_antar=tanggal
    ))
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    _hard_reset_user(user_id, context)

    await update.message.reply_text(
        "🎂 Halo! Selamat datang di *Zee Zee Dessert*!\n\n"
        "Menu kami:\n"
        "• 🥗 Salad Segar — Rp 35.000/buah\n"
        "• 🍮 Pudding Susu — Rp 25.000/buah\n"
        "• 🎁 Dessert Box — Rp 75.000/box\n\n"
        "_Semua pesanan pre-order minimal H-2 ya kak!_ 😊\n\n"
        "Mau pesan apa hari ini?",
        parse_mode="Markdown"
    )


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    _hard_reset_user(user_id, context)
    await update.message.reply_text(
        "🔄 Sesi pesanan direset!\nHalo lagi kak, mau pesan apa? 😊"
    )


async def request_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    customer_name = update.message.from_user.first_name
    set_user_mode(user_id, "waiting")

    await update.message.reply_text(
        "🙏 Baik kak! Saya sedang menghubungkan kakak dengan admin kami.\n"
        "Mohon tunggu sebentar ya! ⏳\n\n"
        "_Ketik /bot kapan saja untuk kembali ke bot._",
        parse_mode="Markdown"
    )

    if ADMIN_CHAT_ID:
        order = get_or_create_order(user_id)
        order_summary = order.rangkuman() if order.items else "Belum ada pesanan."
        notify_msg = format_handoff_notify_admin(
            customer_id=user_id,
            customer_name=customer_name,
            last_message="Customer mengetik /admin",
            order_summary=order_summary
        )
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=notify_msg,
            parse_mode="Markdown"
        )


async def back_to_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    set_user_mode(user_id, "bot")
    await update.message.reply_text(
        "🤖 Kamu sudah terhubung kembali dengan bot kak!\n"
        "Ada yang bisa saya bantu? 😊"
    )


async def cmd_ambil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(str(update.message.from_user.id)):
        await update.message.reply_text("⛔ Kamu bukan admin.")
        return
    if not context.args:
        await update.message.reply_text(
            "❌ Format salah.\nGunakan: /ambil [user_id]\n\nContoh: /ambil 1893576237"
        )
        return
    target_id = context.args[0]
    set_user_mode(target_id, "human")
    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=(
                "✅ *Admin kami sudah siap melayani kakak!*\n"
                "Silakan lanjutkan pertanyaan atau keluhan kamu ya 😊\n\n"
                "_Ketik /bot untuk kembali ke bot kapan saja._"
            ),
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            f"✅ Kamu sekarang handle customer `{target_id}`\n\n"
            f"Perintah selanjutnya:\n"
            f"• `/forward {target_id} [pesan]` → Balas ke customer\n"
            f"• `/selesai {target_id}` → Kembalikan ke bot",
            parse_mode="Markdown"
        )
        print(f"👤 Admin ambil alih customer {target_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal ambil alih: {e}")


async def cmd_selesai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(str(update.message.from_user.id)):
        await update.message.reply_text("⛔ Kamu bukan admin.")
        return
    if not context.args:
        await update.message.reply_text(
            "❌ Format salah.\nGunakan: /selesai [user_id]\n\nContoh: /selesai 1893576237"
        )
        return
    target_id = context.args[0]
    set_user_mode(target_id, "bot")
    conversation_histories.pop(target_id, None)
    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=(
                "✅ Terima kasih sudah menghubungi admin kami kak!\n"
                "Bot siap membantu kamu lagi ya 😊\n\n"
                "Ketik /start untuk memulai pesanan baru."
            )
        )
        await update.message.reply_text(
            f"✅ Customer `{target_id}` sudah dikembalikan ke bot.",
            parse_mode="Markdown"
        )
        print(f"✅ Admin selesai handle customer {target_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(str(update.message.from_user.id)):
        await update.message.reply_text("⛔ Kamu bukan admin.")
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Format salah.\n"
            "Gunakan: /forward [user_id] [pesan]\n\n"
            "Contoh: /forward 1893576237 Halo kak pesanannya sudah kami proses!"
        )
        return
    target_id = context.args[0]
    pesan = " ".join(context.args[1:])
    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=f"👩‍💼 *Admin Zee Zee Dessert:*\n\n{pesan}",
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            f"✅ Pesan terkirim ke `{target_id}`:\n_{pesan}_",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal kirim ke {target_id}: {e}")


async def cmd_list_human(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(str(update.message.from_user.id)):
        await update.message.reply_text("⛔ Kamu bukan admin.")
        return
    active = [
        (uid, mode) for uid, mode in user_modes.items()
        if mode in ("human", "waiting")
    ]
    if active:
        lines = "\n".join([
            f"• `{uid}` — {'🟢 Ditangani admin' if m == 'human' else '🟡 Menunggu admin'}"
            for uid, m in active
        ])
        await update.message.reply_text(
            f"👥 *Customer Aktif ({len(active)} orang):*\n\n{lines}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "✅ Tidak ada customer yang sedang menunggu atau ditangani admin."
        )


async def payment_timeout(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    user_id = data["user_id"]
    total = data["total"]
    order = orders.get(user_id)

    if order and order.status == "verifying_payment":
        await context.bot.send_message(
            chat_id=int(user_id),
            text=(
                "⚠️ *Pembayaran Belum Terdeteksi*\n\n"
                f"Maaf kak, kami belum menerima pembayaran sebesar *Rp {total:,}* dalam 2 menit terakhir.\n\n"
                "Kemungkinan penyebab:\n"
                "• Transfer belum dilakukan\n"
                "• Nominal yang ditransfer tidak sesuai\n"
                "• Rekening tujuan salah\n\n"
                "Silakan cek kembali dan kirim ulang foto bukti transfer ya kak 🙏\n\n"
                "_Atau ketik /admin jika ingin dibantu langsung oleh admin kami._"
            ),
            parse_mode="Markdown"
        )
        order.status = "waiting_payment"
        print(f"⏰ Timeout pembayaran user {user_id} — Rp {total:,}")


async def process_payment_proof(update, context, user_id: str, order):
    if context.job_queue:
        for job in context.job_queue.get_jobs_by_name(f"timeout_{user_id}"):
            job.schedule_removal()

    await update.message.reply_text(
        "📸 Bukti transfer diterima!\n\n"
        "⏳ Sedang memverifikasi pembayaran...\n"
        "Mohon tunggu maksimal *1-2 menit* ya kak 🙏\n\n"
        "_Konfirmasi otomatis akan dikirim setelah terverifikasi._",
        parse_mode="Markdown"
    )

    order.status = "verifying_payment"
    pending_payments[order.total] = user_id

    if context.job_queue:
        context.job_queue.run_once(
            callback=payment_timeout,
            when=120,
            data={"user_id": user_id, "total": order.total},
            name=f"timeout_{user_id}"
        )
        print(f"⏱️  Timeout dijadwalkan untuk user {user_id} dalam 120 detik")
    else:
        print("⚠️  job_queue tidak tersedia. Jalankan: pip install python-telegram-bot[job-queue]")


async def send_payment_confirmation(user_id: str, order, nominal: int, pengirim: str):
    try:
        nama_pemesan = order.nama_pemesan or "Kak"

        await bot_app.bot.send_message(
            chat_id=int(user_id),
            text=(
                f"✅ *Pembayaran Terverifikasi!*\n\n"
                f"Terima kasih kak *{nama_pemesan}*! 🎉\n"
                f"Pembayaran sebesar *Rp {nominal:,}* sudah kami terima.\n\n"
                f"Pesanan kamu sedang kami siapkan ya 🎂\n"
                f"Kami akan menghubungi kamu sebelum tanggal pengiriman."
            ),
            parse_mode="Markdown"
        )

        invoice_path = generate_invoice(order)
        with open(invoice_path, "rb") as f:
            await bot_app.bot.send_document(
                chat_id=int(user_id),
                document=InputFile(f, filename=f"Invoice_ZeeZee_{nama_pemesan}.pdf"),
                caption=(
                    f"📄 *Invoice Pembelian*\n"
                    f"Zee Zee Dessert — {nama_pemesan}\n"
                    f"Total: Rp {nominal:,}\n\n"
                    f"Terima kasih sudah berbelanja! 🎉"
                ),
                parse_mode="Markdown"
            )

        await bot_app.bot.send_message(
            chat_id=int(user_id),
            text=(
                "🛍️ *Pesanan kamu sudah selesai diproses!*\n\n"
                "Terima kasih sudah berbelanja di *Zee Zee Dessert* 💖\n"
                "Semoga dessert-nya bikin hari kamu makin manis! 🎂\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Sesi pemesanan telah berakhir.\n"
                "Ketik /start kapan saja untuk pesan lagi ya! 😊"
            ),
            parse_mode="Markdown"
        )

        if ADMIN_CHAT_ID:
            await bot_app.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=(
                    f"💰 *Pembayaran Masuk Terverifikasi!*\n\n"
                    f"👤 Customer : {nama_pemesan}\n"
                    f"📍 Alamat   : {order.alamat}\n"
                    f"💵 Nominal  : Rp {nominal:,}\n"
                    f"🏦 Dari     : {pengirim}\n\n"
                    f"📋 Detail pesanan:\n{order.rangkuman()}"
                ),
                parse_mode="Markdown"
            )

        try:
            mark_order_paid(
                user_id=user_id,
                order=order,
                pengirim_transfer=pengirim,
                nominal_transfer=nominal
            )
            print(f"📄 Google Sheets updated: pembayaran sukses untuk user {user_id}")
        except Exception as e:
            print(f"⚠️ Gagal update status pembayaran di Google Sheets: {e}")

        _hard_reset_user(user_id)
        print(f"✅ Konfirmasi + invoice terkirim ke user {user_id}")

    except Exception as e:
        print(f"❌ Error send_payment_confirmation: {e}")
        logging.error(f"Error send_payment_confirmation: {e}")


def on_payment_detected_from_gmail(nominal: int, pengirim: str):
    global bot_loop
    print(f"\n📧 Gmail deteksi transfer: Rp {nominal:,} dari {pengirim}")

    matched_user_id = None
    matched_order = None

    for uid, ord in orders.items():
        if ord.status == "verifying_payment" and ord.total == nominal:
            matched_user_id = uid
            matched_order = ord
            break

    if not matched_user_id and nominal in pending_payments:
        matched_user_id = pending_payments.get(nominal)
        if matched_user_id and matched_user_id in orders:
            matched_order = orders[matched_user_id]

    if matched_user_id and matched_order:
        print(f"✅ Match! User: {matched_user_id} | Total: Rp {nominal:,}")
        matched_order.status = "paid"
        matched_order.bukti_transfer = f"Verified via Gmail — Rp {nominal:,} dari {pengirim}"

        if bot_loop and not bot_loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                send_payment_confirmation(matched_user_id, matched_order, nominal, pengirim),
                bot_loop
            )
    else:
        print(f"⚠️  Transfer Rp {nominal:,} tidak cocok dengan order manapun.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    user_text = update.message.text or ""
    customer_name = update.message.from_user.first_name

    if is_admin(user_id):
        await update.message.reply_text(
            "ℹ️ *Perintah admin tersedia:*\n\n"
            "/ambil [user_id] — Ambil alih customer\n"
            "/forward [user_id] [pesan] — Balas ke customer\n"
            "/selesai [user_id] — Kembalikan ke bot\n"
            "/list_human — Lihat customer aktif",
            parse_mode="Markdown"
        )
        return

    mode = get_user_mode(user_id)

    if mode == "waiting":
        await update.message.reply_text(
            "⏳ Sabar ya kak, admin sedang menuju ke sini!\n"
            "Ketik /bot jika ingin kembali dilayani bot."
        )
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"📩 Pesan dari `{customer_name}` ({user_id}) saat menunggu:\n\n_{user_text}_",
                parse_mode="Markdown"
            )
        return

    if mode == "human":
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"💬 *[{customer_name} | {user_id}]:*\n{user_text}",
                parse_mode="Markdown"
            )
        return

    if update.message.photo or update.message.document:
        order = get_or_create_order(user_id)
        if order.status in ("waiting_payment", "verifying_payment"):
            await process_payment_proof(update, context, user_id, order)
        else:
            await update.message.reply_text(
                "Maaf kak, sepertinya belum ada pesanan yang perlu dibayar. "
                "Ketik /start untuk mulai pesan ya! 😊"
            )
        return

    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    await update.message.chat.send_action("typing")

    order = get_or_create_order(user_id)
    ai_response = chat_with_ai(user_id, user_text, conversation_histories[user_id])

    conversation_histories[user_id].append({"role": "user", "content": user_text})
    conversation_histories[user_id].append({"role": "assistant", "content": ai_response.get("pesan", "")})

    if len(conversation_histories[user_id]) > 20:
        conversation_histories[user_id] = conversation_histories[user_id][-20:]

    action = ai_response.get("action", "none")
    response_text = ai_response.get("pesan", "Maaf, ada gangguan. Coba lagi ya kak!")

    if action == "request_human":
        set_user_mode(user_id, "waiting")
        await update.message.reply_text(response_text, parse_mode="Markdown")
        if ADMIN_CHAT_ID:
            order_summary = order.rangkuman() if order.items else "Belum ada pesanan."
            notify_msg = format_handoff_notify_admin(
                customer_id=user_id,
                customer_name=customer_name,
                last_message=user_text,
                order_summary=order_summary
            )
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=notify_msg,
                parse_mode="Markdown"
            )
        return

    elif action == "add_item":
        item_data = ai_response.get("item_data", {})
        _upsert_order_item(order, item_data)

    elif action == "set_identity":
        identity_data = ai_response.get("identity_data", {})
        if identity_data.get("nama_pemesan"):
            order.nama_pemesan = identity_data["nama_pemesan"]
        if identity_data.get("alamat"):
            order.alamat = identity_data["alamat"]

    elif action == "confirm_order":
        try:
            upsert_order_to_sheet(
                user_id=user_id,
                order=order,
                status_pembayaran="menunggu pembayaran"
            )
            print(f"📄 Google Sheets updated: order user {user_id} -> menunggu pembayaran")
        except Exception as e:
            print(f"⚠️ Gagal sync order ke Google Sheets: {e}")

        await update.message.reply_text(response_text, parse_mode="Markdown")
        await update.message.reply_text(order.rangkuman(), parse_mode="Markdown")
        await update.message.reply_text(
            "Apakah data pesanan di atas sudah benar? Ketik *ya* untuk lanjut ke pembayaran. ✅",
            parse_mode="Markdown"
        )
        return

    elif action == "show_payment":
        order.status = "waiting_payment"
        payment_msg = (
            f"{response_text}\n\n"
            f"💳 *Transfer ke:*\n"
            f"🏦 {REKENING['bank']}\n"
            f"📱 No. Rekening: `{REKENING['nomor']}`\n"
            f"👤 A/N: {REKENING['atas_nama']}\n\n"
            f"💰 *Total: Rp {order.total:,}*\n\n"
            f"Setelah transfer, kirimkan _bukti pembayaran_ (foto/screenshot) di sini ya kak! 📸"
        )
        await update.message.reply_text(payment_msg, parse_mode="Markdown")
        pending_payments[order.total] = user_id
        return

    await update.message.reply_text(response_text, parse_mode="Markdown")


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    if is_admin(user_id):
        return

    mode = get_user_mode(user_id)
    if mode == "human":
        if ADMIN_CHAT_ID:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"📎 Customer `{user_id}` mengirim media.",
                parse_mode="Markdown"
            )
        return

    order = get_or_create_order(user_id)
    if order.status in ("waiting_payment", "verifying_payment"):
        await process_payment_proof(update, context, user_id, order)
    else:
        await update.message.reply_text(
            "Maaf kak, sepertinya belum ada pesanan yang perlu dibayar. "
            "Ketik /start untuk mulai pesan ya! 😊"
        )


def main():
    global bot_app, bot_loop

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN tidak ditemukan di .env!")

    app = Application.builder().token(token).build()
    bot_app = app
    bot_loop = asyncio.get_event_loop()

    start_gmail_watcher_thread(on_payment_detected_from_gmail)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("admin", request_admin))
    app.add_handler(CommandHandler("bot", back_to_bot))

    app.add_handler(CommandHandler("ambil", cmd_ambil))
    app.add_handler(CommandHandler("selesai", cmd_selesai))
    app.add_handler(CommandHandler("forward", cmd_forward))
    app.add_handler(CommandHandler("list_human", cmd_list_human))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_media))

    print("🤖 Bot Zee Zee Dessert aktif!")
    print(f"👤 Admin  : {'Aktif — ' + ADMIN_CHAT_ID if ADMIN_CHAT_ID else '⚠️  Belum diset di .env (ADMIN_CHAT_ID)'}")
    jq_status = "Aktif" if app.job_queue else "Nonaktif — jalankan: pip install python-telegram-bot[job-queue]"
    print(f"⏱️  Timeout: {jq_status}")
    print("📊 Google Sheets sync: aktif jika .env dan service account sudah benar")
    app.run_polling()


if __name__ == "__main__":
    main()