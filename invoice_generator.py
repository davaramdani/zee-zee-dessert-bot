# invoice_generator.py
from fpdf import FPDF
from datetime import datetime
import os

class InvoicePDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(220, 50, 100)
        self.cell(0, 10, "ZEE ZEE DESSERT", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 6, "Custom Dessert & Salad | Instagram: @zeezeadessert",
                  align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(4)
        self.set_draw_color(220, 50, 100)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, "Terima kasih telah berbelanja di Zee Zee Dessert!", align="C")

def generate_invoice(order, invoice_number: str = None) -> str:
    pdf = InvoicePDF()
    pdf.add_page()

    if not invoice_number:
        invoice_number = f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Info invoice
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(95, 8, f"INVOICE #{invoice_number}", new_x="RIGHT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(95, 8, f"Tanggal: {datetime.now().strftime('%d %B %Y, %H:%M')}",
             align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Data pemesan
    pdf.set_fill_color(255, 240, 245)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "  Data Pemesan", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(40, 7, "  Nama")
    pdf.cell(0, 7, f": {order.nama_pemesan}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(40, 7, "  Alamat")
    pdf.cell(0, 7, f": {order.alamat}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Header tabel
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "  Detail Pesanan", new_x="LMARGIN", new_y="NEXT")
    pdf.set_fill_color(220, 50, 100)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(10, 8, "No", fill=True, border=1)
    pdf.cell(70, 8, "Item", fill=True, border=1)
    pdf.cell(30, 8, "Tgl Antar", fill=True, border=1)
    pdf.cell(20, 8, "Qty", fill=True, border=1, align="C")
    pdf.cell(30, 8, "Harga", fill=True, border=1, align="R")
    pdf.cell(30, 8, "Subtotal", fill=True, border=1, align="R",
             new_x="LMARGIN", new_y="NEXT")

    # Isi tabel
    pdf.set_text_color(50, 50, 50)
    pdf.set_font("Helvetica", "", 10)
    for i, item in enumerate(order.items, 1):
        fill = (i % 2 == 0)
        if fill:
            pdf.set_fill_color(255, 248, 250)
        else:
            pdf.set_fill_color(255, 255, 255)
        pdf.cell(10, 7, str(i), fill=fill, border=1)
        pdf.cell(70, 7, item.nama, fill=fill, border=1)
        pdf.cell(30, 7, item.tanggal_antar, fill=fill, border=1)
        pdf.cell(20, 7, str(item.jumlah), fill=fill, border=1, align="C")
        pdf.cell(30, 7, f"Rp {item.harga_satuan:,}", fill=fill, border=1, align="R")
        pdf.cell(30, 7, f"Rp {item.subtotal:,}", fill=fill, border=1, align="R",
                 new_x="LMARGIN", new_y="NEXT")

    # Total
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(255, 230, 240)
    pdf.cell(160, 9, "TOTAL PEMBAYARAN", fill=True, border=1, align="R")
    pdf.cell(30, 9, f"Rp {order.total:,}", fill=True, border=1, align="R",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Konfirmasi pembayaran
    pdf.set_fill_color(240, 255, 240)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "  PEMBAYARAN DITERIMA", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, f"  Waktu konfirmasi: {datetime.now().strftime('%d %B %Y, %H:%M WIB')}",
             new_x="LMARGIN", new_y="NEXT")

    os.makedirs("invoices", exist_ok=True)
    filepath = f"invoices/invoice_{order.user_id}_{invoice_number}.pdf"
    pdf.output(filepath)
    return filepath