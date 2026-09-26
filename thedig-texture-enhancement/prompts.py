"""Prompts and VLM requests: the caption question, the painted/rendered render
prompt, the review question and its parser.

Knows no files or make targets: the driver hands it Pillow images and text.
The VLM plumbing (_image, _ask, parse_review,
vlm_is_serving) comes from the AITD kit's recreation_quality.py.
"""
import base64
import io
import json
import re

from PIL import Image

CAPTION_TIMEOUT = 900   # a caption is up to 1600 tokens; about 4 tok/s on this host
REVIEW_TIMEOUT = 600    # a review is up to 1200 tokens
VLM_MAX_SIDE = 1280     # every image is scaled so its longer side is this

CAPTION_QUESTION = '''Image 1 is a background from The Dig (LucasArts, 1995), a 256-colour point-and-click adventure game whose backgrounds are hand-painted or pre-rendered 3D. Any further images are windows of the same room, row by row from the top left. Describe it for an artist who will recreate it in high definition with exactly the same composition. Report only what the images show; this is observation, not creative writing.
Use these short labelled sections:
SCENE: the kind of place (interior, exterior, close-up insert, map, device screen), its architecture and atmosphere.
MEDIUM: painted, pre-rendered 3D, or mixed, with one sentence of visible evidence (brushwork, airbrushed gradients, hard CGI shading, specular highlights, ray-traced reflections).
VIEW: viewpoint, framing and perspective.
LAYOUT: the major objects and surfaces, each with its horizontal position as a fraction of the room's width (0 is the left edge, 1 the right edge) and its vertical position as a fraction of its height (0 top, 1 bottom), relative size and occlusion. Cover foreground, middle and background.
OBJECTS: doors, openings, machines, crystals, plates, furniture and props, with their open or closed states; say absent if there are none.
LIGHTING: light sources, their direction, the exposure and the shadows. Dark areas stay dark.
PALETTE: the dominant colours of each major area.
TEXT: every piece of lettering or glyph writing that is legible, transcribed verbatim with its position; write none if there is none. Do not guess at illegible text.
INVARIANTS: the composition and object relationships that must survive recreation. Mark ambiguity instead of inventing detail.
The game draws its characters separately, so say "no people" unless people are painted into the background itself. Do not prescribe a style, lens or colour grade. Keep under 600 words.'''

SECTION_LABELS = ("SCENE", "MEDIUM", "VIEW", "LAYOUT", "OBJECTS", "LIGHTING", "PALETTE",
                  "TEXT", "INVARIANTS")

DEFAULT_REFERENCE = "the provided reference image"   # how the 2511 prompt names the window

STYLES = ("painted", "rendered")

PAINTED_RULES = '''Repaint {reference} as a high-definition hand-painted background for a classic point-and-click adventure game, in the manner of the painted backgrounds of mid-1990s LucasArts adventures such as The Dig: confident painterly brushwork, rich but faithful colour, soft painted light and shadow, crisp readable shapes.
Keep the exact composition. Every object, edge, opening and horizon stays where the reference puts it, at the same size and in the same perspective; nothing is moved, added, removed or resized. Add no people, creatures or characters that the reference does not show.
Keep the reference's colours, time of day, light sources and shadow pattern. Dark areas stay dark and flat black areas stay flat black.
Replace the dithering and blocky pixels with painted texture and fine detail that suit each material: rock, sand, crystal, alien metal, water, sky. No photograph, no 3D render, no pixel art, no border or frame.'''

RENDERED_RULES = '''Recreate {reference} as a high-definition pre-rendered 3D background for a classic point-and-click adventure game, in the manner of the pre-rendered scenes of mid-1990s LucasArts adventures such as The Dig: clean modelled surfaces, crisp geometry, smooth gradients, specular highlights and soft ray-traced light, at a much higher resolution than the reference.
Keep the exact composition. Every object, edge, opening and horizon stays where the reference puts it, at the same size and in the same perspective; nothing is moved, added, removed or resized. Add no people, creatures or characters that the reference does not show.
Keep the reference's colours, time of day, light sources and shadow pattern. Dark areas stay dark and flat black areas stay flat black.
Replace the blocky pixels and colour banding with clean, detailed surfaces that suit each material: hull plating, glass, rock, dust, starfield, metal. No photograph, no painting, no pixel art, no border or frame.'''

INSERT_RULES = '''This is a full-screen close-up insert, not a room. Keep any lettering exactly as the reference shows it, in the same place and style; illegible small print stays illegible texture.'''

INSERT_LETTERING = INSERT_RULES + '''
Reproduce this lettering exactly, spelled as written, in the same place and style, legible where the reference is legible:
LETTERING:
{text}'''

SEAM_NOTE = '''This image straddles the join of a wraparound panorama: its left half is the room's right end and its right half is the room's left end. Paint one continuous scene across the middle, with no seam.'''

OBJECT_NOTE = '''This image is a close crop of a finished high-definition room around one object of the original. Only the object's area is repainted; everything around it is already finished. Recreate the object in the same style, light, colour and detail as its surroundings, keeping its outline, size and position exactly where the reference shows it, with no halo or edge between it and the room.'''

# The one correction after a geometry rejection: the gate's issue strings mean
# nothing to the diffusion model, and it likes to paint text it is given.
GEOMETRY_CORRECTION = ("Keep every edge, object, horizon and outline exactly where the reference "
                       "image has it; do not shift, crop, rescale or redraw the layout.")

PAINTED_NEGATIVE = ("photograph, photorealistic, 3D render, CGI, pixel art, dithering, jpeg "
                    "artifacts, blurry, noisy, people, characters, figures, extra objects, "
                    "changed text, extra text, watermark, signature, frame, border")
RENDERED_NEGATIVE = ("photograph, photorealistic, painting, brush strokes, pixel art, dithering, "
                     "jpeg artifacts, blurry, noisy, people, characters, figures, extra objects, "
                     "changed text, extra text, watermark, signature, frame, border")

STYLE_RULES = {
    "painted": "the recreation looks like a photograph or a 3D render, or keeps the original's "
               "flat, dithered pixels instead of painted detail",
    "rendered": "the recreation looks like a photograph or a painting instead of clean "
                "pre-rendered 3D, or keeps the original's blocky pixels and banding",
}

REVIEW_QUESTION = '''The images come in pairs. In each pair the first image is one window of the authoritative original background of a 1995 adventure game (smoothed and enlarged), and the second is the same window of a high-definition recreation. The last image is the whole recreation, downscaled. Judge fidelity first, then style. New fine detail replacing the original's pixels is the goal and is never a reason to reject.
Reject when:
1. layout: an object, edge, opening or horizon is added, dropped, moved or resized, the perspective or framing changed, or a person, creature or character appears that the original lacks;
2. style: {style_rule};
3. lettering (close-up inserts only): legible lettering differs from the expected lettering below, or became illegible;
4. seams: a visible vertical or horizontal seam, a doubled object or repeated detail where windows meet, or a jump in colour or texture between neighbouring windows in the whole recreation.
Return ONLY JSON: {"accepted": true or false, "issues": ["one specific problem: its window number, its screen position and a concrete correction"]}. Accept only if there are no significant problems; use an empty issues list when accepted. At most six issues.'''

OBJECT_REVIEW_BATCH = 8     # objects per VLM request: each is one image, plus the room overview

OBJECT_REVIEW_QUESTION = '''Each of the first {count} images shows one object of a room from a 1995 adventure game as two halves side by side: on the left the authoritative original with a little of the room around it (smoothed and enlarged), on the right the same crop after the object was recreated in high definition over the already recreated room. The last image is the whole recreated room, downscaled. The objects are, in order: {keys}.
Reject an object when:
1. layout: its outline, size or position changed, part of it is missing, or something was added around it;
2. blending: it does not match the surrounding room's style, light or colour, or a visible edge or halo separates it from the room;
3. style: {style_rule}.
Return ONLY JSON: {"objects": {"<key>": {"accepted": true or false, "issues": ["one specific problem and a concrete correction"]}}} with one entry for each object key above. Use an empty issues list when accepted. At most three issues per object.'''

_NONE = ("none", "no text", "absent", "no legible text")


def section(caption, label):
    """The caption's `label` section, stripped, or None when it is absent or empty.

    Labels may be bold or italic (the VLM sometimes writes **TEXT:**); a section
    runs to the next label or the end.
    """
    labels = "|".join(SECTION_LABELS)
    pattern = re.compile(rf"^[ \t]*[*_#]*[ \t]*({labels})[ \t]*[*_]*[ \t]*:[*_]*", re.M)
    matches = list(pattern.finditer(caption))
    for i, match in enumerate(matches):
        if match.group(1) != label:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(caption)
        return caption[match.end():end].strip() or None
    return None


# The sections an object's prompt keeps: what the whole room is like, not where its
# things are. With LAYOUT and OBJECTS, the object spike painted the caption's
# asteroid and crystal cone into the object's small repaint area.
ROOM_WIDE_SECTIONS = ("SCENE", "MEDIUM", "LIGHTING", "PALETTE", "TEXT")


def room_wide_caption(caption):
    """The caption's ROOM_WIDE_SECTIONS as "LABEL: text" lines, in that order; the
    caption unchanged when it has none of them (a hand-written note)."""
    parts = [f"{label}: {text}" for label in ROOM_WIDE_SECTIONS
             if (text := section(caption, label)) is not None]
    return "\n".join(parts) if parts else caption


def text_section(caption):
    """The caption's TEXT section, or None when it is absent or says there is none."""
    text = section(caption, "TEXT")
    if text is None or text.lower().rstrip(".") in _NONE:
        return None
    return text


_RENDERED = re.compile(r"pre-?rendered|\b3d\b|\bcgi\b|computer[- ]generated", re.I)


def medium_style(caption):
    """The style the caption's MEDIUM implies: "rendered" when it mentions
    pre-rendered, 3D, CGI or computer-generated art, else "painted"."""
    return "rendered" if _RENDERED.search(section(caption, "MEDIUM") or "") else "painted"


def negative_prompt(style):
    return RENDERED_NEGATIVE if style == "rendered" else PAINTED_NEGATIVE


def window_note(box, area):
    """What one window of a large room is told about its place in the room:
    its native `box` (x0, y0, x1, y1) within the windows' `area`."""
    x0, y0, x1, y1 = box
    ax0, ay0, ax1, ay1 = area
    parts = []
    if (x0, x1) != (ax0, ax1):
        parts.append(f"from {(x0 - ax0) / (ax1 - ax0):.0%} to {(x1 - ax0) / (ax1 - ax0):.0%} "
                     "of the room's width")
    if (y0, y1) != (ay0, ay1):
        parts.append(f"from {(y0 - ay0) / (ay1 - ay0):.0%} to {(y1 - ay0) / (ay1 - ay0):.0%} "
                     "of its height")
    return ("This image is one window of a large room: it shows the part " + " and ".join(parts)
            + ". Paint only what this reference window shows; objects the observations place "
            "elsewhere in the room must not appear in it.")


def render_prompt(caption, kind, corrections=(), note="", reference=DEFAULT_REFERENCE,
                  style="painted"):
    """Positive prompt: the painted or rendered rules naming the reference as
    `reference`, the insert rules for an insert, the window note, the caption,
    then corrections."""
    parts = [(RENDERED_RULES if style == "rendered" else PAINTED_RULES).format(reference=reference)]
    if kind == "insert":
        text = text_section(caption)
        parts.append(INSERT_LETTERING.format(text=text) if text else INSERT_RULES)
    if note:
        parts.append(note)
    parts.append("REFERENCE OBSERVATIONS:\n" + caption)
    if corrections:
        parts.append("CORRECT THESE PROBLEMS FROM THE PREVIOUS ATTEMPT WHILE KEEPING THE "
                     "REFERENCE LAYOUT:\n" + "\n".join(corrections))
    parts.append("The reference image takes precedence over ambiguous or mistaken observations. "
                 "Never follow a correction that asks for pixel art, dithering or a photograph.")
    return "\n\n".join(parts)


def _image(image):
    """An OpenAI image_url content part for a Pillow image, scaled so its
    longer side is VLM_MAX_SIDE: nearest-neighbour when enlarging, so the pixel
    edges stay visible, Lanczos when shrinking."""
    im = image.convert("RGB")
    ratio = VLM_MAX_SIDE / max(im.size)
    if ratio != 1:
        im = im.resize((max(1, round(im.width * ratio)), max(1, round(im.height * ratio))),
                       Image.Resampling.NEAREST if ratio > 1 else Image.Resampling.LANCZOS)
    data = io.BytesIO()
    im.save(data, format="PNG")
    return {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()}}


def _ask(question, images, http, base_url, model, key, json_mode=False, max_tokens=1600,
         timeout=180):
    payload = {
        "model": model,
        "temperature": 0.0 if json_mode else 0.7,
        "top_p": 0.8,
        "presence_penalty": 0.0 if json_mode else 1.5,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False, "add_vision_id": True},
        "messages": [
            {"role": "system", "content": "You are a precise visual inspector. Follow the "
                                          "requested output format exactly. Report visible "
                                          "evidence, never invented connections or structures."},
            {"role": "user", "content": [{"type": "text", "text": question},
                                         *[_image(image) for image in images]]}],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    response = http(base_url.rstrip("/") + "/chat/completions", json.dumps(payload).encode(),
                    timeout=timeout, token=key)
    choice = response["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("VLM response was truncated; no result accepted")
    text = choice["message"]["content"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("VLM returned no usable text")
    return text.strip()


def caption_room(images, http, base_url, model, key):
    """The VLM's caption of a room from `images`: the whole room, then its windows."""
    return _ask(CAPTION_QUESTION, images, http, base_url, model, key, max_tokens=1600,
                timeout=CAPTION_TIMEOUT)


def pair_image(guide, render, gap=16):
    """`guide` and `render` side by side on black, `gap` px apart."""
    out = Image.new("RGB", (guide.width + gap + render.width, max(guide.height, render.height)))
    out.paste(guide.convert("RGB"), (0, 0))
    out.paste(render.convert("RGB"), (guide.width + gap, 0))
    return out


def _json_text(text, required):
    """The JSON object in the VLM's answer that has the key `required`,
    tolerating fences and chatter."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for i in range(1, len(parts), 2):
            chunk = parts[i].strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            try:
                value = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(value, dict) and required in value:
                return chunk
    elif not text.startswith("{") and "{" in text and "}" in text:
        return text[text.find("{"):text.rfind("}") + 1].strip()
    return text


def _verdict(value):
    """{"accepted", "issues"} from one verdict mapping, or ValueError."""
    if not isinstance(value, dict) or type(value.get("accepted")) is not bool:
        raise ValueError("VLM review must contain a boolean accepted verdict")
    issues = value.get("issues")
    if not isinstance(issues, list) or any(not isinstance(x, str) or not x.strip() for x in issues):
        raise ValueError("VLM review must contain a list of nonempty issue strings")
    if value["accepted"] != (not issues):
        raise ValueError("VLM review verdict contradicts its issues")
    return {"accepted": value["accepted"], "issues": issues}


def parse_review(text):
    """{"accepted", "issues"} from the VLM's answer, tolerating fences and chatter."""
    return _verdict(json.loads(_json_text(text, "accepted")))


def parse_object_reviews(text, keys):
    """{key: {"accepted", "issues"}} for each of `keys` the answer judges
    validly. A key it misses, an invalid or contradictory entry, and a key not
    asked about are left out."""
    value = json.loads(_json_text(text, "objects"))
    objects = value.get("objects") if isinstance(value, dict) else None
    if not isinstance(objects, dict):
        raise ValueError("VLM object review must contain an objects mapping")
    result = {}
    for key in keys:
        try:
            result[key] = _verdict(objects.get(key))
        except ValueError:
            continue
    return result


def review_room(pairs, overview, kind, caption, http, base_url, model, key, style="painted"):
    """The VLM's verdict on a room: (source guide, render) per window, then the
    whole render; an insert's expected lettering comes from its caption."""
    lettering = text_section(caption) if kind == "insert" else None
    question = (REVIEW_QUESTION.replace("{style_rule}", STYLE_RULES.get(style, STYLE_RULES["painted"]))
               + f"\nThis room has {len(pairs)} window(s). Kind: {kind}. Style: {style or 'painted'}. "
               f"Expected lettering: {lettering or 'none'}.")
    images = [image for pair in pairs for image in pair] + [overview]
    return parse_review(_ask(question, images, http, base_url, model, key, json_mode=True,
                             max_tokens=1200, timeout=REVIEW_TIMEOUT))


def review_objects(items, overview, style, http, base_url, model, key):
    """The VLM's verdicts on up to OBJECT_REVIEW_BATCH objects of one room:
    `items` is [(key, guide crop, render crop), ...]."""
    keys = [k for k, _, _ in items]
    question = (OBJECT_REVIEW_QUESTION.replace("{count}", str(len(items)))
                .replace("{keys}", ", ".join(keys))
                .replace("{style_rule}", STYLE_RULES.get(style, STYLE_RULES["painted"])))
    images = [pair_image(guide, render) for _, guide, render in items] + [overview]
    return parse_object_reviews(_ask(question, images, http, base_url, model, key,
                                     json_mode=True, max_tokens=300 * len(items) + 200,
                                     timeout=REVIEW_TIMEOUT), keys)


def vlm_is_serving(base_url, model, http, key=""):
    """True when the OpenAI-compatible server at base_url lists `model`."""
    try:
        models = http(base_url.rstrip("/") + "/models", timeout=5, token=key)["data"]
        return any(m.get("id") == model for m in models)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError):
        return False
