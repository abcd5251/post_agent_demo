"""Write marketing copy, build image prompts, generate images and host them."""

import base64
import re

import cloudinary
import cloudinary.uploader
import cloudinary.utils

import config
from .common import env, log


def _clean(text):
    """FB/IG show markdown as raw text: drop inline citations and unwrap links/bold."""
    text = re.sub(r"\s*\(\[[^\]]*\]\([^)]*\)\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return text.strip()


def write_copy(client, style, research, rss_text):
    prompt = config.COPY_PROMPT.format(
        style_name=style["name"], style_instructions=style["instructions"],
        research=research, rss=rss_text)
    copy = _clean(client.responses.create(model=config.TEXT_MODEL, input=prompt).output_text)
    if not copy:
        raise RuntimeError(f"empty copy for style {style['name']}")
    return copy


def make_image_prompt(client, style, copy):
    prompt = config.IMAGE_PROMPT_TEMPLATE.format(copy=copy, image_style=style["image_style"])
    text = client.responses.create(model=config.TEXT_MODEL, input=prompt).output_text.strip()
    return f"{text}\n{config.IMAGE_PROMPT_SUFFIX}"


def generate_image(client, image_prompt):
    """Return PNG bytes."""
    result = client.images.generate(model=config.IMAGE_MODEL, prompt=image_prompt,
                                    size=config.IMAGE_SIZE)
    return base64.b64decode(result.data[0].b64_json)


def upload_image(png_bytes, public_id):
    """Upload to Cloudinary and return a public JPEG URL that IG accepts (4:5 ~ 1.91:1)."""
    cloudinary.config(
        cloud_name=env("CLOUDINARY_CLOUD_NAME"),
        api_key=env("CLOUDINARY_API_KEY"),
        api_secret=env("CLOUDINARY_API_SECRET"),
        secure=True,
    )
    data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    result = cloudinary.uploader.upload(
        data_uri, folder=config.CLOUDINARY_FOLDER, public_id=public_id, overwrite=True,
        resource_type="image")
    # Pad (never crop) anything narrower than 4:5; square/landscape images are untouched.
    width, height = result["width"], result["height"]
    transformation = []
    if width / height < 0.8:
        transformation = [{"crop": "pad", "aspect_ratio": "4:5", "background": "white"}]
    url, _ = cloudinary.utils.cloudinary_url(
        result["public_id"], format="jpg", secure=True, transformation=transformation or None)
    log(f"image uploaded: {url}")
    return url
