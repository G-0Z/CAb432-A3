import os, io, json, time, traceback
import boto3
from PIL import Image, ImageOps, ImageDraw, ImageFont

REGION    = "ap-southeast-2"
BUCKET    = "maxgo-cab432-2025"
QUEUE_URL = "https://sqs.ap-southeast-2.amazonaws.com/901444280953/image-processing-queue-n11543027"

s3  = boto3.client("s3", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)

def log(*a): print(*a, flush=True)

def to_rgb(img: Image.Image) -> Image.Image:
    return img.convert("RGB") if img.mode != "RGB" else img

def apply_preset(img: Image.Image, mode: str, params: dict) -> Image.Image:
    img = to_rgb(img)
    if mode == "grayscale":
        return ImageOps.grayscale(img).convert("RGB")
    if mode == "resize":
        w = int(params.get("width") or 0) or img.width
        h = int(params.get("height") or 0) or img.height
        return img.resize((max(1,w), max(1,h)), Image.Resampling.LANCZOS)
    if mode == "rotate":
        deg = int(params.get("deg") or 90)
        return img.rotate(-deg, expand=True)
    if mode == "thumb":
        size = (256, 256)
        im = img.copy()
        im.thumbnail(size, Image.Resampling.LANCZOS)
        bg = Image.new("RGB", size, (245,245,245))
        bg.paste(im, ((size[0]-im.width)//2, (size[1]-im.height)//2))
        return bg
    if mode == "watermark":
        text = str(params.get("text") or "©")
        overlay = img.copy()
        draw = ImageDraw.Draw(overlay)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", max(16, img.width//20))
        except Exception:
            font = ImageFont.load_default()
        tw, th = draw.textbbox((0,0), text, font=font)[2:]
        pad = max(10, img.width//100)
        x = img.width - tw - pad
        y = img.height - th - pad
        draw.rectangle([x-pad, y-pad, x+tw+pad, y+th+pad], fill=(0,0,0,96))
        draw.text((x, y), text, font=font, fill=(255,255,255,220))
        return overlay
    return img

def process_one(key: str, mode: str, params: dict):
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    data = obj["Body"].read()
    img = Image.open(io.BytesIO(data))
    img = apply_preset(img, mode, params)

    fname = os.path.basename(key)
    out_key = f"processed/{fname}"

    buf = io.BytesIO()
    ext = (os.path.splitext(fname)[1] or "").lower()
    fmt = "PNG" if ext == ".png" else "JPEG"
    img.save(buf, format=fmt, quality=92)
    buf.seek(0)

    s3.put_object(Bucket=BUCKET, Key=out_key, Body=buf.getvalue(),
                  ContentType="image/png" if fmt=="PNG" else "image/jpeg")
    log("processed:", out_key)

def main():
    log("worker started; polling…")
    while True:
        try:
            resp = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=5,
                WaitTimeSeconds=10,
                VisibilityTimeout=120,
            )
            msgs = resp.get("Messages", [])
            if not msgs:
                continue
            for m in msgs:
                body = m["Body"]
                try:
                    msg = json.loads(body)
                    key    = msg.get("key")
                    mode   = (msg.get("mode") or "grayscale").lower()
                    params = msg.get("params") or {}
                except Exception:
                    key, mode, params = body, "grayscale", {}
                if not key or not key.startswith("uploads/"):
                    sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=m["ReceiptHandle"])
                    continue
                try:
                    log("processing:", key, mode, params)
                    process_one(key, mode, params)
                except Exception as e:
                    log("error:", key, e)
                    traceback.print_exc()
                finally:
                    sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=m["ReceiptHandle"])
            time.sleep(0.3)
        except Exception as e:
            log("loop error:", e)
            traceback.print_exc()
            time.sleep(2)

if __name__ == "__main__":
    main()
