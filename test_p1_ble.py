import argparse
import asyncio
from pathlib import Path

from bleak import BleakScanner, BleakClient
from PIL import Image

# Python utility for P1 BLE Thermal printer
# from https://portableprinter.en.made-in-china.com/product/VphUcBgohzkR/China-Portable-Wireless-Wireless-Thermal-Label-Printer-2-Inch-Instant-Receipt-Barcode-Qr-Code-Printer-Label-Maker-with-Templates-for-Inventory-Shipping.html

# BLE device name and writable characteristic for this printer model.
DEVICE_NAME = "P1_0EE1"
WRITE_CHAR = "00002af1-0000-1000-8000-00805f9b34fb"

# 40x50 mm label stock at 8 dots/mm yields a 320x400 dot canvas.
LABEL_WIDTH_MM = 40
LABEL_HEIGHT_MM = 50

DOTS_PER_MM = 8

LABEL_WIDTH_DOTS = LABEL_WIDTH_MM * DOTS_PER_MM
LABEL_HEIGHT_DOTS = LABEL_HEIGHT_MM * DOTS_PER_MM

QR_SIZES = {
    "s": 5,
    "m": 7,
    "l": 9,
}

BARCODE_TYPES = {
    "code128": "128",
    "code39": "39",
    "ean13": "EAN13",
    "upca": "UPCA",
}

LEFT_MARGIN = 20

# Logo and title are arranged across the top row, left-aligned from this margin.
LOGO_SIZE = 60
LOGO_X = LEFT_MARGIN
LOGO_Y = 0

TITLE_Y = 16
TITLE_GAP_AFTER_LOGO = 8

# Coordinates are tuned per QR size so caption and info stay visible below the code.
LAYOUTS = {
    "s": {
        "qr_x": 95,
        "qr_y": 75,
        "caption_y": 235,
        "info_y": 275,
    },
    "m": {
        "qr_x": 60,
        "qr_y": 75,
        "caption_y": 285,
        "info_y": 325,
    },
    "l": {
        "qr_x": 25,
        "qr_y": 75,
        "caption_y": 345,
        "info_y": 385,
    },
}

BARCODE_LAYOUT = {
    "barcode_x": 30,
    "barcode_y": 95,
    "barcode_height": 120,
    "caption_y": 245,
    "info_y": 285,
}

def chunks(data, n=20):
    # BLE writes are kept small; 20 bytes is the safe packet size here.
    for i in range(0, len(data), n):
        yield data[i:i+n]

def clean_tspl_text(text):
    if text is None:
        return None
    # Prevent quotes and line breaks from corrupting TSPL commands.
    return text.replace('"', "'").replace("\r", " ").replace("\n", " ")

def truncate_text(text, max_chars):
    if text is None:
        return None

    if len(text) <= max_chars:
        return text

    if max_chars <= 3:
        return text[:max_chars]

    return text[:max_chars - 3] + "..."

def base_header():
    # TSPL setup: define stock, clear the page, and keep density consistent.
    return (
        f"SIZE {LABEL_WIDTH_MM} mm,{LABEL_HEIGHT_MM} mm\r\n"
        "GAP 2 mm,0 mm\r\n"
        "DENSITY 8\r\n"
        "DIRECTION 0\r\n"
        "CLS\r\n"
    ).encode("utf-8")

def add_text(payload, x, y, font, xmul, ymul, text):
    text = clean_tspl_text(text)
    return payload + f'TEXT {x},{y},"{font}",0,{xmul},{ymul},"{text}"\r\n'.encode("utf-8")

def add_bold_text(payload, x, y, font, xmul, ymul, text):
    # Simulate bold by printing the same text twice with a 1-dot offset.
    payload = add_text(payload, x, y, font, xmul, ymul, text)
    payload = add_text(payload, x + 1, y, font, xmul, ymul, text)
    return payload

def add_barcode(payload, x, y, code_type, height, human_readable, narrow, wide, text):
    text = clean_tspl_text(text)
    human = 1 if human_readable else 0
    return payload + (
        f'BARCODE {x},{y},"{code_type}",{height},{human},0,{narrow},{wide},"{text}"\r\n'
    ).encode("utf-8")

def image_to_tspl_bitmap_bytes(image_path, size=60, invert=False):
    """
    Convert a logo image to TSPL 1-bit bitmap bytes.

    The visible image fits inside size x size.
    The bitmap canvas width is padded to a multiple of 8 because
    TSPL BITMAP width is specified in bytes.

    Default:
      dark pixels -> black print
      light pixels -> white background

    Use --logo-invert only if the printed result needs reversing.
    """
    path = Path(image_path)

    if not path.exists():
        raise FileNotFoundError(f"Logo file not found: {image_path}")

    with Image.open(path) as source_image:
        img = source_image.convert("RGBA")

    # Flatten transparency onto white so PNG logos print predictably.
    bg = Image.new("RGBA", img.size, "WHITE")
    bg.alpha_composite(img)
    img = bg.convert("L")

    # Fit into the requested visible area while preserving aspect ratio.
    img.thumbnail((size, size), Image.Resampling.LANCZOS)

    # TSPL BITMAP width is measured in bytes, so the pixel width must be padded to /8.
    canvas_width = ((size + 7) // 8) * 8
    canvas_height = size

    canvas = Image.new("L", (canvas_width, canvas_height), 255)

    x = (canvas_width - img.width) // 2
    y = (canvas_height - img.height) // 2
    canvas.paste(img, (x, y))

    threshold = 160
    bw = canvas.point(lambda p: 0 if p < threshold else 255, "L")

    width_bytes = canvas_width // 8
    data = bytearray()

    for row in range(canvas_height):
        for byte_x in range(width_bytes):
            value = 0

            for bit in range(8):
                px = byte_x * 8 + bit
                pixel = bw.getpixel((px, row))

                is_black = pixel == 0

                if invert:
                    is_black = not is_black

                # For this printer, 1 bits print black.
                if is_black:
                    value |= 0x80 >> bit

            data.append(value)

    return width_bytes, canvas_height, bytes(data)

def add_logo_bitmap(payload, logo_path, x=LOGO_X, y=LOGO_Y, size=LOGO_SIZE, invert=False):
    width_bytes, height, bitmap_data = image_to_tspl_bitmap_bytes(
        logo_path,
        size=size,
        invert=invert
    )

    payload += f"BITMAP {x},{y},{width_bytes},{height},0,".encode("utf-8")
    payload += bitmap_data
    payload += b"\r\n"

    return payload

def title_max_chars(title_x):
    # Rough estimate for TSPL font 3 at xmul=1.
    right_margin = 10
    available_width = LABEL_WIDTH_DOTS - title_x - right_margin

    # Font 3 is roughly 16 dots wide per character at xmul=1.
    approx_char_width = 16

    return max(1, available_width // approx_char_width)

def make_text_label(lines):
    # Plain text mode prints one line per row using built-in font 3.
    payload = base_header()

    y = 20
    for line in lines:
        payload = add_text(payload, LEFT_MARGIN, y, "3", 1, 1, line)
        y += 40

    payload += b"PRINT 1\r\n"
    return payload

def make_qr_label(
    qr_text,
    title=None,
    caption=None,
    info=None,
    qr_size="s",
    logo=None,
    logo_invert=False
):
    qr_text = clean_tspl_text(qr_text)
    title = clean_tspl_text(title)
    caption = clean_tspl_text(caption)
    info = clean_tspl_text(info)

    cell_width = QR_SIZES[qr_size]
    layout = LAYOUTS[qr_size]

    payload = base_header()

    # Keep the top row reserved for logo + title so QR content starts below it.
    if logo:
        payload = add_logo_bitmap(
            payload,
            logo,
            LOGO_X,
            LOGO_Y,
            LOGO_SIZE,
            invert=logo_invert
        )
        title_x = LOGO_X + LOGO_SIZE + TITLE_GAP_AFTER_LOGO
    else:
        title_x = LEFT_MARGIN

    # Truncate the title to the width that remains after the logo.
    if title:
        max_chars = title_max_chars(title_x)
        title = truncate_text(title, max_chars)

        payload = add_bold_text(
            payload,
            x=title_x,
            y=TITLE_Y,
            font="3",
            xmul=1,
            ymul=1,
            text=title
        )

    payload += (
        f'QRCODE {layout["qr_x"]},{layout["qr_y"]},L,{cell_width},A,0,"{qr_text}"\r\n'
    ).encode("utf-8")

    if caption:
        payload = add_text(
            payload,
            x=LEFT_MARGIN,
            y=layout["caption_y"],
            font="2",
            xmul=1,
            ymul=1,
            text=caption
        )

    if info:
        payload = add_text(
            payload,
            x=LEFT_MARGIN,
            y=layout["info_y"],
            font="1",
            xmul=1,
            ymul=1,
            text=info
        )

    payload += b"PRINT 1\r\n"

    print("Layout:")
    print(f"  label dots: {LABEL_WIDTH_DOTS} x {LABEL_HEIGHT_DOTS}")
    print(f"  qr size: {qr_size}, cell width: {cell_width}")
    print(f"  logo: {logo if logo else '(none)'}")
    print(f"  logo_x: {LOGO_X}, logo_y: {LOGO_Y}, logo_size: {LOGO_SIZE}")
    print(f"  logo_invert: {logo_invert}")
    print(f"  title_x: {title_x}, title_y: {TITLE_Y}")
    print(f"  qr_x: {layout['qr_x']}, qr_y: {layout['qr_y']}")
    print(f"  caption_y: {layout['caption_y']}")
    print(f"  info_y: {layout['info_y']}")

    return payload

def validate_barcode_text(barcode_text, barcode_type):
    if barcode_type in {"ean13", "upca"} and not barcode_text.isdigit():
        raise ValueError(f"{barcode_type.upper()} requires numeric data only.")

    if barcode_type == "ean13" and len(barcode_text) != 13:
        raise ValueError("EAN13 requires exactly 13 digits.")

    if barcode_type == "upca" and len(barcode_text) != 12:
        raise ValueError("UPCA requires exactly 12 digits.")

def make_barcode_label(
    barcode_text,
    title=None,
    caption=None,
    info=None,
    barcode_type="code128",
    logo=None,
    logo_invert=False
):
    validate_barcode_text(barcode_text, barcode_type)

    barcode_text = clean_tspl_text(barcode_text)
    title = clean_tspl_text(title)
    caption = clean_tspl_text(caption)
    info = clean_tspl_text(info)

    payload = base_header()

    # Barcode labels reserve the same top row for logo + title as QR labels.
    if logo:
        payload = add_logo_bitmap(
            payload,
            logo,
            LOGO_X,
            LOGO_Y,
            LOGO_SIZE,
            invert=logo_invert
        )
        title_x = LOGO_X + LOGO_SIZE + TITLE_GAP_AFTER_LOGO
    else:
        title_x = LEFT_MARGIN

    if title:
        max_chars = title_max_chars(title_x)
        title = truncate_text(title, max_chars)

        payload = add_bold_text(
            payload,
            x=title_x,
            y=TITLE_Y,
            font="3",
            xmul=1,
            ymul=1,
            text=title
        )

    payload = add_barcode(
        payload,
        x=BARCODE_LAYOUT["barcode_x"],
        y=BARCODE_LAYOUT["barcode_y"],
        code_type=BARCODE_TYPES[barcode_type],
        height=BARCODE_LAYOUT["barcode_height"],
        human_readable=True,
        narrow=2,
        wide=4,
        text=barcode_text
    )

    if caption:
        payload = add_text(
            payload,
            x=LEFT_MARGIN,
            y=BARCODE_LAYOUT["caption_y"],
            font="2",
            xmul=1,
            ymul=1,
            text=caption
        )

    if info:
        payload = add_text(
            payload,
            x=LEFT_MARGIN,
            y=BARCODE_LAYOUT["info_y"],
            font="1",
            xmul=1,
            ymul=1,
            text=info
        )

    payload += b"PRINT 1\r\n"

    print("Layout:")
    print(f"  label dots: {LABEL_WIDTH_DOTS} x {LABEL_HEIGHT_DOTS}")
    print(f"  barcode type: {barcode_type}")
    print(f"  barcode data: {barcode_text}")
    print(f"  logo: {logo if logo else '(none)'}")
    print(f"  logo_x: {LOGO_X}, logo_y: {LOGO_Y}, logo_size: {LOGO_SIZE}")
    print(f"  logo_invert: {logo_invert}")
    print(f"  title_x: {title_x}, title_y: {TITLE_Y}")
    print(f"  barcode_x: {BARCODE_LAYOUT['barcode_x']}, barcode_y: {BARCODE_LAYOUT['barcode_y']}")
    print(f"  barcode_height: {BARCODE_LAYOUT['barcode_height']}")
    print(f"  caption_y: {BARCODE_LAYOUT['caption_y']}")
    print(f"  info_y: {BARCODE_LAYOUT['info_y']}")

    return payload

async def print_payload(payload):
    print("Scanning for printer...")
    devices = await BleakScanner.discover(timeout=8)
    target = next((d for d in devices if d.name == DEVICE_NAME), None)

    if not target:
        print("Printer not found. Close Eleph-label/LightBlue and try again.")
        return

    print("Connecting to", target.name)

    async with BleakClient(target.address) as client:
        print("Connected")

        # Pace writes slightly to avoid overrunning the printer over BLE.
        for c in chunks(payload):
            await client.write_gatt_char(WRITE_CHAR, c, response=False)
            await asyncio.sleep(0.08)

        print("Sent")
        await asyncio.sleep(2)

def main():
    parser = argparse.ArgumentParser(
        description="Print labels to P1_0EE1 over BLE using TSPL."
    )

    # Positional arguments are used for simple text-label mode.
    parser.add_argument("text", nargs="*", help="Text line(s) to print")
    # `--qr` switches the script into QR-label mode.
    parser.add_argument("--qr", help="QR code content to print")
    parser.add_argument("--barcode", help="Barcode content to print")

    parser.add_argument(
        "--title",
        "--tittle",
        dest="title",
        help="Title printed above the QR code in larger simulated-bold text"
    )

    parser.add_argument(
        "--logo",
        help="Path to a logo image. It will be resized to 60x60 dots and printed beside the title."
    )

    parser.add_argument(
        "--logo-invert",
        action="store_true",
        help="Invert logo bitmap before printing. Use only if your logo prints reversed."
    )

    parser.add_argument("--caption", help="Caption printed below the QR code")
    parser.add_argument("--info", help="Smaller info text printed below the caption")

    parser.add_argument(
        "--qr-size",
        choices=["s", "m", "l"],
        default="s",
        help="QR size: s, m, or l. s=5, m=7, l=9."
    )

    parser.add_argument(
        "--barcode-type",
        choices=list(BARCODE_TYPES),
        default="code128",
        help="Barcode type: code128, code39, ean13, or upca."
    )

    args = parser.parse_args()

    selected_modes = sum(bool(mode) for mode in (args.qr, args.barcode, args.text))
    if selected_modes > 1:
        parser.error("Choose exactly one label mode: text, --qr, or --barcode.")

    if args.qr:
        payload = make_qr_label(
            qr_text=args.qr,
            title=args.title,
            caption=args.caption,
            info=args.info,
            qr_size=args.qr_size,
            logo=args.logo,
            logo_invert=args.logo_invert
        )
    elif args.barcode:
        payload = make_barcode_label(
            barcode_text=args.barcode,
            title=args.title,
            caption=args.caption,
            info=args.info,
            barcode_type=args.barcode_type,
            logo=args.logo,
            logo_invert=args.logo_invert
        )
    elif args.text:
        payload = make_text_label(args.text)
    else:
        parser.print_help()
        return

    asyncio.run(print_payload(payload))

if __name__ == "__main__":
    main()
