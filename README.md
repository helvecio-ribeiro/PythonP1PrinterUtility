# PythonP1PrinterUtility

Control the `P1` Bluetooth thermal label printer directly from Python over BLE, without depending on the vendor's `Eleph-label` software.

> [!IMPORTANT]
> This utility exists to make the printer usable from any operating system that can run Python and talk to Bluetooth Low Energy, instead of being limited by the default `Eleph-label` workflow.

## What This Is

This repository contains a small Python utility that builds `TSPL` printer commands and sends them over `BLE` to a portable `P1` thermal printer. It supports:

- Simple text labels
- QR code labels
- 1D barcode labels
- Optional title, caption, and info lines
- Optional logo rendering as a 1-bit bitmap

The target hardware appears to match the public `P1` product listing here:

- Product page: <https://portableprinter.en.made-in-china.com/product/VphUcBgohzkR/China-Portable-Wireless-Wireless-Thermal-Label-Printer-2-Inch-Instant-Receipt-Barcode-Qr-Code-Printer-Label-Maker-with-Templates-for-Inventory-Shipping.html>

That listing describes a Bluetooth thermal label printer marketed for QR codes, barcodes, storage labels, and similar lightweight labeling tasks.

## Why It Exists

Many small thermal printers ship with mobile-first or vendor-specific software that makes automation awkward and cross-platform use harder than it should be. This utility takes a simpler route:

- Generate the label payload locally
- Send it directly to the printer over BLE
- Keep the workflow scriptable on macOS, Linux, or Windows

If you want to print labels from your own scripts, local tools, or automation workflows, this project is the missing layer between Python and the printer.

## Hardware Notes

The current script is tuned for a printer exposed as:

- Device name: `P1_0EE1`
- Writable characteristic: `00002af1-0000-1000-8000-00805f9b34fb`

The label layout is currently configured around:

- Label size: `40 x 50 mm`
- Density: `8 dots/mm`
- Canvas: `320 x 400 dots`

These values are easy to change in `test_p1_ble.py` if your unit advertises a different BLE name or if you want to retune layout constants.

## Setup

Install dependencies:

```bash
./setup_venv.sh
```

Activate the virtual environment before running the utility:

```bash
source .venv/bin/activate
```

Or install the dependencies manually from `requirements.txt`.

## Usage

Before printing:

- Make sure the printer is powered on and nearby
- Close `Eleph-label`, `LightBlue`, or any other app already connected to the printer over BLE
- Use the virtual environment created by `setup_venv.sh` or ensure `bleak` and `Pillow` are installed in your active Python
- Expect BLE permissions and pairing behavior to vary across macOS, Linux, and Windows

Print a simple text label:

```bash
python test_p1_ble.py "Hello" "P1 printer"
```

Print a QR label with title, caption, and logo:

```bash
python test_p1_ble.py \
  --qr "https://example.com" \
  --title "Inventory Tag" \
  --caption "Scan for details" \
  --info "Batch A-14" \
  --logo grupo_spitia_small.png
```

Print a barcode label using the default `CODE128` mode:

```bash
python test_p1_ble.py \
  --barcode "ITEM-00042" \
  --title "Inventory Label" \
  --caption "Warehouse shelf B3"
```

For numeric-only retail barcode types, use `--barcode-type`:

```bash
python test_p1_ble.py \
  --barcode "123456789012" \
  --barcode-type upca \
  --title "Retail SKU"
```

Barcode rules:

- `code128` is the default and accepts general text
- `code39` accepts alphanumeric barcode content in a simpler 1D format
- `ean13` requires exactly `13` numeric digits
- `upca` requires exactly `12` numeric digits

## Code Notes

The script is intentionally compact, but there are a few implementation details worth documenting for anyone extending it:

| Area | Why it matters |
| --- | --- |
| Bitmap thresholding | The logo conversion uses a fixed grayscale threshold for 1-bit output. This is a tuning value, not a universal constant. |
| QR layouts | QR coordinates are hand-tuned per size so captions and footer text remain visible on the fixed label canvas. |
| Barcode layout | Barcode placement and height are currently tuned for the same 40 x 50 mm stock and may need adjustment for different media. |
| BLE pacing | Writes are chunked and slightly delayed because this printer is sensitive to send rate over BLE. |
| Title width | Title truncation is based on an approximate font-width heuristic, not exact text measurement. |
| `--tittle` alias | The CLI accepts both `--title` and `--tittle`; the second spelling should be treated as compatibility behavior unless intentionally removed. |
| Layout debug output | The script prints layout values during QR generation to help with real-world label calibration. |

## Scope

This is a practical utility for a specific class of low-cost portable thermal printers, not a general printer driver. If the hardware protocol differs on your unit, expect to adjust:

- BLE discovery name
- Writable characteristic UUID
- TSPL layout constants
- Packet pacing

The current values were observed from one working `P1` device profile and should not be assumed to be universal across every printer sold under similar branding.

## Troubleshooting

- If the printer is not found, first close `Eleph-label`, `LightBlue`, or any other BLE tool that may already be holding the connection
- If discovery still fails, confirm your printer advertises the same BLE name as the one configured in `test_p1_ble.py`
- If text or graphics print in the wrong position, retune the layout constants for your label stock and printer behavior
- If a logo prints inverted or with poor contrast, try `--logo-invert` or adjust the bitmap threshold in the script
- If `ean13` or `upca` input is rejected, verify the data is numeric and the required fixed length

## Reference

- Printer listing used for device identification and public context: <https://portableprinter.en.made-in-china.com/product/VphUcBgohzkR/China-Portable-Wireless-Wireless-Thermal-Label-Printer-2-Inch-Instant-Receipt-Barcode-Qr-Code-Printer-Label-Maker-with-Templates-for-Inventory-Shipping.html>
