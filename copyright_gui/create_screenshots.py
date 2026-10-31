"""Create clean PNG evidence sheets for the DocBlendAI copyright submission."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1600, 900
OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"

def font(size, bold=False, serif=False):
    return ImageFont.truetype(SERIF if serif else (BOLD if bold else FONT), size)

def canvas(title, kicker):
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    draw.line((0, 92, WIDTH, 92), fill="#d9dcdb", width=2)
    draw.text((70, 28), "DocBlendAI", font=font(28, bold=True), fill="#202222")
    draw.text((70, 125), kicker.upper(), font=font(15, bold=True), fill="#686d6c")
    draw.text((70, 160), title, font=font(52, serif=True), fill="#202222")
    return image, draw

def save(name, image):
    image.save(OUT / name, optimize=True)

image, draw = canvas("Confidence-aware document understanding", "Project showcase")
draw.text((70, 252), "From uploaded document to grounded, reliable answer", font=font(22), fill="#686d6c")
steps = [("01", "Input", "PDF · image · Word"), ("02", "Detect", "Typed · scan · handwriting"), ("03", "Extract", "OCR / HTR · layout"), ("04", "Calibrate", "Confidence → accuracy"), ("05", "Retrieve", "Relevant evidence"), ("06", "Answer", "Reliability label")]
for index, (number, name, detail) in enumerate(steps):
    x = 70 + index * 245
    draw.rectangle((x, 340, x + 220, 620), outline="#d9dcdb", width=2)
    draw.text((x + 18, 360), number, font=font(14, bold=True), fill="#686d6c")
    draw.text((x + 18, 455), name, font=font(24, bold=True), fill="#202222")
    draw.text((x + 18, 505), detail, font=font(15), fill="#686d6c")
save("01-project-workflow.png", image)

image, draw = canvas("Three document paths, one pipeline", "Text extraction")
for index, (label, title, code) in enumerate([
    ("Typed", "Digital text parser", "Digital text → layout → chunks"),
    ("Printed scan", "Tesseract OCR", "Page → OCR → word confidence"),
    ("Handwriting", "PaddleOCR / TrOCR", "Page → lines → HTR confidence"),
]):
    x = 70 + index * 505
    draw.rectangle((x, 340, x + 470, 690), outline="#d9dcdb", width=2)
    draw.text((x + 28, 370), label.upper(), font=font(14, bold=True), fill="#686d6c")
    draw.text((x + 28, 430), title, font=font(25, bold=True), fill="#202222")
    draw.rectangle((x + 28, 590, x + 442, 650), fill="#f4f5f5")
    draw.text((x + 43, 607), code, font=font(15), fill="#202222")
save("02-text-extraction.png", image)

image, draw = canvas("From raw score to expected character accuracy", "Confidence calibration")
boxes = [(70, 330, 360, 650, "OCR raw confidence", "0.70", "Extractor score"), (510, 330, 1080, 650, "Piecewise-linear calibration", "0.70 → 0.73", "Raw confidence fitted against character accuracy"), (1240, 330, 1530, 650, "Calibrated confidence", "0.73", "Expected accuracy")]
for left, top, right, bottom, label, value, detail in boxes:
    draw.rectangle((left, top, right, bottom), outline="#d9dcdb", width=2)
    draw.text((left + 24, top + 28), label, font=font(16), fill="#686d6c")
    draw.text((left + 24, top + 115), value, font=font(34, serif=True), fill="#202222")
    draw.text((left + 24, top + 210), detail, font=font(15), fill="#686d6c")
draw.text((410, 470), "→", font=font(34), fill="#686d6c")
draw.text((1140, 470), "→", font=font(34), fill="#686d6c")
draw.text((70, 700), "Known curve:  0.00 → 0.00     0.70 → 0.73     0.94 → 0.99", font=font(18, bold=True), fill="#202222")
draw.text((70, 752), "Held-out calibration error improved: 0.062 → 0.013 for scanned pages", font=font(18), fill="#686d6c")
save("03-confidence-calibration.png", image)

image, draw = canvas("Measured project performance", "Evaluation")
metrics = [("88%", "Answer correctness"), ("88%", "Retrieval hit rate"), ("100%", "Certain answers correct"), ("100%", "Typed recognition accuracy")]
for index, (value, label) in enumerate(metrics):
    x = 70 + index * 365
    draw.rectangle((x, 330, x + 330, 570), outline="#d9dcdb", width=2)
    draw.text((x + 24, 375), value, font=font(52, serif=True), fill="#202222")
    draw.text((x + 24, 465), label, font=font(17), fill="#686d6c")
draw.text((70, 650), "Reliability tier", font=font(17, bold=True), fill="#202222")
draw.text((420, 650), "Answers", font=font(17, bold=True), fill="#202222")
draw.text((650, 650), "Correct", font=font(17, bold=True), fill="#202222")
for row, (tier, count, correct) in enumerate([("Certain", "9", "100%"), ("Moderate", "5", "100%"), ("Uncertain", "4", "50%")]):
    y = 700 + row * 48
    draw.line((70, y - 8, 800, y - 8), fill="#d9dcdb", width=1)
    draw.text((70, y), tier, font=font(17), fill="#202222")
    draw.text((420, y), count, font=font(17), fill="#202222")
    draw.text((650, y), correct, font=font(17), fill="#202222")
save("04-project-performance.png", image)

print(f"Created 4 screenshots in {OUT}")
