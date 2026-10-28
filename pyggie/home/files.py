# home/files.py — turn uploaded files into something the model can read
import base64, io
from .models import Attachment
from . import ollama

MAX_BYTES = 10 * 1024 * 1024     # per file
MAX_FILES = 5
MAX_CHARS = 60000                # text given to the model per file
IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}


def save_attachments(message, uploads):
    """Extract text from each upload and store it. Returns a list of error strings."""
    errors = []
    for f in uploads[:MAX_FILES]:
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if f.size > MAX_BYTES:
            errors.append(f"{f.name}: larger than 10 MB"); continue
        raw = f.read()
        try:
            if ext in IMAGE_EXT:
                Attachment.objects.create(message=message, name=f.name, kind="image",
                                          image_b64=base64.b64encode(raw).decode())
                continue
            if ext == "pdf":
                from pypdf import PdfReader
                text = "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
                if not text.strip():
                    errors.append(f"{f.name}: no text found (scanned PDF?)"); continue
                kind = "pdf"
            else:
                if b"\x00" in raw[:4096]:
                    errors.append(f"{f.name}: binary file, not supported"); continue
                text, kind = raw.decode("utf-8", errors="replace"), "text"
        except Exception as e:
            errors.append(f"{f.name}: {e}"); continue
        note = ""
        if len(text) > MAX_CHARS:
            text, note = text[:MAX_CHARS], f"\n[…truncated, file has more than {MAX_CHARS} characters]"
        Attachment.objects.create(message=message, name=f.name, kind=kind, text=text + note)
    if len(uploads) > MAX_FILES:
        errors.append(f"only the first {MAX_FILES} files were used")
    return errors


def _describe(a, vision_model):
    """Description of an image attachment from the chosen vision model, cached on the attachment
    (Attachment.text, stored as '<vision model>\\0<description>', so a new vision model re-describes)."""
    if a.text.startswith(vision_model + "\0"):
        return a.text.split("\0", 1)[1]
    desc = ollama.describe_image(vision_model, a.image_b64)
    if not desc:
        raise RuntimeError("the vision model returned no description")
    a.text = vision_model + "\0" + desc
    a.save(update_fields=["text"])
    return desc


def build_history(chat, caps=(), vision_model=""):
    """Chat history for the model, with attachments folded into the user messages.

    Images: if `vision_model` is set, it describes each image first and the chat model only
    receives that text. Otherwise images go straight to the chat model if it can see them."""
    out = []
    for m in chat.messages.filter(role__in=["user", "ai"]).prefetch_related("attachments"):
        if m.role == "ai":
            out.append({"role": "assistant", "content": m.content}); continue
        content, images = m.content, []
        for a in m.attachments.all():
            if a.kind == "image":
                if vision_model:
                    try:
                        content += f"\n\n[Attached image {a.name}, described by a vision model:]\n{_describe(a, vision_model)}"
                    except Exception as e:
                        content += f"\n\n[Attached image {a.name}: the vision model could not describe it ({ollama.friendly_error(e)})]"
                elif "vision" in caps: images.append(a.image_b64)
                else: content += f"\n\n[Attached image {a.name}: this model cannot see images]"
            else:
                content += f"\n\n[Attached file: {a.name}]\n```\n{a.text}\n```"
        msg = {"role": "user", "content": content}
        if images: msg["images"] = images
        out.append(msg)
    return out
