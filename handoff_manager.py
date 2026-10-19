# handoff_manager.py
import re

def format_handoff_notify_admin(customer_id, customer_name, last_message, order_summary):
    return (
        f"🔔 *CUSTOMER MINTA CHAT LANGSUNG*\n\n"
        f"👤 Nama: {customer_name}\n"
        f"🆔 ID: `{customer_id}`\n"
        f"💬 Pesan terakhir: _{last_message}_\n\n"
        f"📋 Ringkasan pesanan:\n{order_summary}\n\n"
        f"──────────────────────\n"
        f"*Perintah admin:*\n"
        f"• `/ambil {customer_id}` → Mulai handle\n"
        f"• `/forward {customer_id} [pesan]` → Balas ke customer\n"
        f"• `/selesai {customer_id}` → Kembalikan ke bot\n"
        f"• `/list_human` → Lihat semua customer aktif"
    )

def is_handoff_command(text: str):
    """
    Parse perintah admin dari teks pesan.
    Return: (is_command, command, target_id, extra)
    """
    text = text.strip()

    # /ambil [user_id]
    m = re.match(r'^/ambil\s+(\d+)$', text, re.IGNORECASE)
    if m:
        return True, "ambil", m.group(1), ""

    # /selesai [user_id]
    m = re.match(r'^/selesai\s+(\d+)$', text, re.IGNORECASE)
    if m:
        return True, "selesai", m.group(1), ""

    # /forward [user_id] [pesan] — pesan boleh mengandung spasi
    m = re.match(r'^/forward\s+(\d+)\s+(.+)$', text, re.IGNORECASE | re.DOTALL)
    if m:
        # Bersihkan tanda [ ] jika ada: /forward 123 [pesan] → pesan
        pesan = m.group(2).strip().strip('[]')
        return True, "forward", m.group(1), pesan

    # /list_human
    if re.match(r'^/list_human$', text, re.IGNORECASE):
        return True, "list_human", "", ""

    return False, "", "", ""