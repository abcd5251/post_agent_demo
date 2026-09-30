"""Search the latest news on config_openai.TOPIC with OpenAI, summarize it,
generate an image, and publish both to the Facebook Page and Instagram.

Scheduling works like post.py: it waits until config_openai.POST_TIME, posts
once, then idles (Render free web service, see render.yaml).

Usage:
    python post_openai.py            # wait until POST_TIME, post once
    python post_openai.py --now      # generate and post immediately
    python post_openai.py --dry-run  # generate summary + image locally, post nothing
"""

import argparse
import base64
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

import config_openai as cfg
import post
from post import BASE_DIR, env, log

TZ = ZoneInfo(cfg.TIMEZONE)
POST_TIME = datetime.strptime(cfg.POST_TIME, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
OUTPUT_DIR = BASE_DIR / "generated"
MARKER = cfg.HASHTAGS[0]


def strip_citations(text):
    """web_search adds inline citations like ([cna.com.tw](https://...)); FB/IG
    show markdown as raw text, so drop them (and unwrap any other markdown links)."""
    text = re.sub(r"\s*\(\[[^\]]*\]\([^)]*\)\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text.strip()


def has_english(text):
    """True if text contains any Latin word (2+ letters)."""
    return re.search(r"[A-Za-z]{2,}", text) is not None


def generate_content(image_path=None):
    """Return (caption, image_path) generated from the latest news.
    The image is saved to image_path, or to generated/news_<timestamp>.png."""
    client = OpenAI(api_key=env("OPENAI_API_KEY"))

    log(f"searching news for {cfg.TOPIC!r} with {cfg.TEXT_MODEL}...")
    response = client.responses.create(
        model=cfg.TEXT_MODEL,
        tools=[{"type": "web_search"}],
        input=cfg.SUMMARY_PROMPT.format(topic=cfg.TOPIC),
    )
    summary = strip_citations(response.output_text)
    if has_english(summary):
        log("summary contains English, translating to Chinese...")
        summary = strip_citations(client.responses.create(
            model=cfg.TEXT_MODEL,
            input=cfg.TRANSLATE_PROMPT.format(text=summary),
        ).output_text)
    caption = f"{summary}\n\n{cfg.DISCLAIMER}\n{' '.join(cfg.HASHTAGS)}"
    log(f"caption ({len(caption)} chars):\n{caption}")

    scene = client.responses.create(
        model=cfg.TEXT_MODEL,
        input=cfg.IMAGE_SCENE_PROMPT.format(summary=summary),
    ).output_text.strip()
    log(f"generating image with {cfg.IMAGE_MODEL}, scene: {scene}")
    image = client.images.generate(
        model=cfg.IMAGE_MODEL,
        prompt=cfg.IMAGE_PROMPT.format(scene=scene),
        size=cfg.IMAGE_SIZE,
    )
    image_path = image_path or OUTPUT_DIR / f"news_{datetime.now(TZ):%Y%m%d_%H%M%S}.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(base64.b64decode(image.data[0].b64_json))
    log(f"image saved: {image_path}")
    return caption, image_path


def make_job(since):
    """Build a job for post.run_at(). Content is generated once and reused on retries."""
    content = {}

    def job():
        page_id = env("META_PAGE_ID")
        ig_id = env("META_INSTAGRAM_ACCOUNT_ID")
        page_token = env("META_PAGE_ACCESS_TOKEN")
        post.check_token(page_token, page_id)

        # The caption changes every run, so detect "already posted" by the marker hashtag.
        todo = []
        if cfg.POST_TO_FACEBOOK:
            if post.already_on_facebook(page_id, page_token, MARKER, since):
                log("Facebook: already posted, skipping.")
            else:
                todo.append("Facebook")
        if cfg.POST_TO_INSTAGRAM:
            if post.already_on_instagram(ig_id, page_token, MARKER, since):
                log("Instagram: already posted, skipping.")
            else:
                todo.append("Instagram")
        if not todo:
            return []

        if not content:
            content["caption"], content["image"] = generate_content()
        caption, image_path = content["caption"], content["image"]

        failures = []
        if "Facebook" in todo:
            try:
                post.post_facebook(page_id, page_token, caption, image_path)
            except Exception as e:
                failures.append(f"Facebook: {e}")
        if "Instagram" in todo:
            try:
                image_url = post.upload_to_cloudinary(image_path)
                post.post_instagram(ig_id, page_token, caption, image_url)
            except Exception as e:
                failures.append(f"Instagram: {e}")
        for failure in failures:
            log(f"[error] {failure}")
        return failures

    return job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", action="store_true", help="ignore POST_TIME, post now")
    parser.add_argument("--dry-run", action="store_true",
                        help="generate summary + image locally, post nothing")
    args = parser.parse_args()

    if args.dry_run:
        generate_content()
        log("dry run complete, nothing posted.")
        return
    if args.now:
        sys.exit(1 if make_job(datetime.now(TZ))() else 0)

    post.run_at(POST_TIME, cfg.WINDOW_MINUTES, make_job(POST_TIME))


if __name__ == "__main__":
    main()
