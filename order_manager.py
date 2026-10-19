# order_manager.py
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")

@dataclass
class ItemPesanan:
    nama: str
    jumlah: int
    harga_satuan: int
    tanggal_antar: str

    @property
    def subtotal(self):
        return self.jumlah * self.harga_satuan

@dataclass
class Pesanan:
    user_id: str
    items: List[ItemPesanan] = field(default_factory=list)
    nama_pemesan: Optional[str] = None
    alamat: Optional[str] = None
    status: str = "ordering"
    waktu_pesan: datetime = field(default_factory=datetime.now)
    bukti_transfer: Optional[str] = None

    @property
    def total(self):
        return sum(item.subtotal for item in self.items)

    def rangkuman(self):
        lines = ["📋 *RANGKUMAN PESANAN*\n"]
        for i, item in enumerate(self.items, 1):
            lines.append(
                f"{i}. {item.nama} x{item.jumlah} "
                f"(tanggal: {item.tanggal_antar})"
                f"\n   Rp {item.harga_satuan:,} × {item.jumlah} = Rp {item.subtotal:,}"
            )
        lines.append(f"\n👤 Nama: {self.nama_pemesan}")
        lines.append(f"📍 Alamat: {self.alamat}")
        lines.append(f"\n💰 *TOTAL: Rp {self.total:,}*")
        return "\n".join(lines)

# In-memory storage
orders: Dict[str, Pesanan] = {}
user_modes: Dict[str, str] = {}  # "bot" | "waiting" | "human"

def get_or_create_order(user_id: str) -> Pesanan:
    if user_id not in orders:
        orders[user_id] = Pesanan(user_id=user_id)
    return orders[user_id]

def reset_order(user_id: str):
    orders.pop(user_id, None)

def get_user_mode(user_id: str) -> str:
    return user_modes.get(user_id, "bot")

def set_user_mode(user_id: str, mode: str):
    user_modes[user_id] = mode