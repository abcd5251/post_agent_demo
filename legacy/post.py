"""Publish assets/text.txt + assets/image.png to the Facebook Page and Instagram.

Posting time and options live in config.py. Deployed as a Render *free* web
service (see render.yaml): on start it waits until POST_TIME, posts once, then
goes idle so Render spins it down. While waiting it pings its own public URL
every 10 minutes, because free services sleep after 15 minutes without traffic.
If it starts late (redeploy / restart) but within WINDOW_MINUTES of POST_TIME it
posts right away; platforms that already have the same caption are skipped.

Usage:
    python post.py            # wait until POST_TIME, post once
    python post.py --now      # post immediately, ignore POST_TIME
    python post.py --dry-run  # validate config/token/assets, post nothing
"""

import argparse
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import cloudinary
import cloudinary.uploader
import requests
from dotenv import load_dotenv

import config

BASE_DIR = Path(__file__).resolve().parent.parent  # repo root (assets/, .env)
TEXT_FILE = BASE_DIR / config.TEXT_FILE
IMAGE_FILE = BASE_DIR / config.IMAGE_FILE
TZ = ZoneInfo(config.TIMEZONE)
POST_TIME = datetime.strptime(config.POST_TIME, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)

load_dotenv(BASE_DIR / ".env")


def env(name, default=None, required=True):
    value = os.getenv(name, default)
    if required and not value:
        sys.exit(f"[error] missing environment variable: {name}")
    return value


API_VERSION = env("META_API_VERSION", "v20.0")
GRAPH = f"https://graph.facebook.com/{API_VERSION}"


def log(msg):
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{now}] {msg}", flush=True)


def graph_call(method, path, **kwargs):
    resp = requests.request(method, f"{GRAPH}/{path}", timeout=120, **kwargs)
    data = resp.json()
    if resp.status_code != 200 or "error" in data:
        raise RuntimeError(f"Graph API {method} /{path} failed: {data}")
    return data


def load_assets():
    if not TEXT_FILE.exists() or not IMAGE_FILE.exists():
        sys.exit(f"[error] need both {TEXT_FILE} and {IMAGE_FILE}")
    caption = TEXT_FILE.read_text(encoding="utf-8").strip()
    return caption, IMAGE_FILE


def check_token(page_token, page_id):
    app_token = f"{env('META_APP_ID')}|{env('META_APP_SECRET')}"
    info = graph_call(
        "GET", "debug_token",
        params={"input_token": page_token, "access_token": app_token},
    )["data"]
    if not info.get("is_valid"):
        sys.exit(f"[error] META_PAGE_ACCESS_TOKEN is invalid: {info.get('error')}")
    if info.get("type") != "PAGE" or str(info.get("profile_id")) != str(page_id):
        log(f"[warn] token type={info.get('type')} profile_id={info.get('profile_id')}"
            f" (expected PAGE token for {page_id})")
    expires = info.get("expires_at", 0)
    expiry = "never" if not expires else datetime.fromtimestamp(expires, TZ).isoformat()
    log(f"token OK, scopes={info.get('scopes')}, expires={expiry}")


def post_facebook(page_id, page_token, caption, image_path):
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    with open(image_path, "rb") as f:
        data = graph_call(
            "POST", f"{page_id}/photos",
            data={"message": caption, "published": "true", "access_token": page_token},
            files={"source": (image_path.name, f, mime)},
        )
    log(f"Facebook posted: post_id={data.get('post_id')} photo_id={data.get('id')}")
    return data


def upload_to_cloudinary(image_path):
    cloudinary.config(
        cloud_name=env("CLOUDINARY_CLOUD_NAME"),
        api_key=env("CLOUDINARY_API_KEY"),
        api_secret=env("CLOUDINARY_API_SECRET"),
        secure=True,
    )
    result = cloudinary.uploader.upload(
        str(image_path),
        folder=env("CLOUDINARY_UPLOAD_FOLDER", "auto_posting"),
        resource_type="image",
    )
    # IG feed images must be JPEG with aspect ratio between 4:5 and 1.91:1.
    # Pad (not crop) to 4:5 so nothing in the photo gets cut off.
    url, _ = cloudinary.utils.cloudinary_url(
        result["public_id"],
        secure=True,
        format="jpg",
        transformation=[{"crop": "pad", "aspect_ratio": "4:5", "background": "white",
                         "width": 1080, "quality": "auto"}],
    )
    log(f"Cloudinary URL: {url}")
    return url


def post_instagram(ig_id, page_token, caption, image_url):
    container = graph_call(
        "POST", f"{ig_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": page_token},
    )["id"]
    log(f"IG container created: {container}")

    for _ in range(30):
        status = graph_call(
            "GET", container,
            params={"fields": "status_code,status", "access_token": page_token},
        )
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"IG container {container} failed: {status}")
        time.sleep(5)
    else:
        raise RuntimeError(f"IG container {container} not ready after 150s")

    data = graph_call(
        "POST", f"{ig_id}/media_publish",
        data={"creation_id": container, "access_token": page_token},
    )
    log(f"Instagram posted: media_id={data.get('id')}")
    return data


def _parse_graph_time(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")


def already_on_facebook(page_id, page_token, text, since=POST_TIME):
    """True if the Page has a post containing `text` created at/after `since`."""
    posts = graph_call(
        "GET", f"{page_id}/published_posts",
        params={"fields": "message,created_time", "limit": 25, "access_token": page_token},
    ).get("data", [])
    return any(
        text in (p.get("message") or "")
        and _parse_graph_time(p["created_time"]) >= since
        for p in posts
    )


def already_on_instagram(ig_id, page_token, text, since=POST_TIME):
    """True if the IG account has media whose caption contains `text`, at/after `since`."""
    media = graph_call(
        "GET", f"{ig_id}/media",
        params={"fields": "caption,timestamp", "limit": 25, "access_token": page_token},
    ).get("data", [])
    return any(
        text in (m.get("caption") or "")
        and _parse_graph_time(m["timestamp"]) >= since
        for m in media
    )


def publish(dry_run=False):
    """Post to the enabled platforms once. Returns a list of failure messages."""
    page_id = env("META_PAGE_ID")
    ig_id = env("META_INSTAGRAM_ACCOUNT_ID")
    page_token = env("META_PAGE_ACCESS_TOKEN")
    caption, image_path = load_assets()
    log(f"caption ({len(caption)} chars):\n{caption}")

    check_token(page_token, page_id)
    if dry_run:
        log("dry run complete, nothing posted.")
        return []

    # Run both platforms even if one fails.
    failures = []
    if config.POST_TO_FACEBOOK:
        try:
            if already_on_facebook(page_id, page_token, caption):
                log("Facebook: already posted, skipping.")
            else:
                post_facebook(page_id, page_token, caption, image_path)
        except Exception as e:
            failures.append(f"Facebook: {e}")
    if config.POST_TO_INSTAGRAM:
        try:
            if already_on_instagram(ig_id, page_token, caption):
                log("Instagram: already posted, skipping.")
            else:
                post_instagram(ig_id, page_token, caption, upload_to_cloudinary(image_path))
        except Exception as e:
            failures.append(f"Instagram: {e}")

    for failure in failures:
        log(f"[error] {failure}")
    return failures


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"scheduled post at {config.POST_TIME} {config.TIMEZONE}\n".encode())

    def log_message(self, *args):
        pass


def start_health_server(port):
    server = ThreadingHTTPServer(("0.0.0.0", int(port)), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"health server listening on :{port}")


def keep_awake(url, stop):
    while not stop.wait(600):
        try:
            requests.get(url, timeout=30)
            log("keep-awake ping")
        except requests.RequestException as e:
            log(f"[warn] keep-awake ping failed: {e}")


def run_at(post_time, window_minutes, job, attempts=3):
    """Wait until post_time, run job() once (retrying while it returns failures),
    then idle so a Render free web service can spin down.

    job() returns a list of failure messages (empty == success). If we start
    after post_time + window_minutes, the job is skipped.
    """
    # Render web services must listen on $PORT; locally there is no PORT.
    port = os.getenv("PORT")
    if port:
        start_health_server(port)

    deadline = post_time + timedelta(minutes=window_minutes)
    now = datetime.now(post_time.tzinfo)
    if now >= deadline:
        log(f"post time {post_time:%Y-%m-%d %H:%M %Z} has passed; nothing to do.")
    else:
        stop_pinging = threading.Event()
        external_url = os.getenv("RENDER_EXTERNAL_URL")
        if external_url and now < post_time:
            threading.Thread(target=keep_awake, args=(external_url, stop_pinging),
                             daemon=True).start()

        log(f"waiting until {post_time:%Y-%m-%d %H:%M %Z}...")
        while (remaining := (post_time - datetime.now(post_time.tzinfo)).total_seconds()) > 0:
            time.sleep(min(remaining, 60))

        # Retry failed platforms a couple of times; already-posted ones are skipped.
        for attempt in range(1, attempts + 1):
            try:
                failures = job()
            except Exception as e:
                failures = [str(e)]
                log(f"[error] {e}")
            if not failures:
                log("all done.")
                break
            if attempt < attempts:
                log(f"attempt {attempt} had failures, retrying in 60s...")
                time.sleep(60)
        stop_pinging.set()

    if port:
        # Exiting would make Render restart the service; idle instead and let
        # the free instance spin down once no more traffic arrives.
        log("idle; Render will spin this service down.")
        threading.Event().wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", action="store_true", help="ignore POST_TIME, post now")
    parser.add_argument("--dry-run", action="store_true", help="validate only, post nothing")
    args = parser.parse_args()

    if args.dry_run or args.now:
        sys.exit(1 if publish(dry_run=args.dry_run) else 0)

    run_at(POST_TIME, config.WINDOW_MINUTES, publish)


if __name__ == "__main__":
    main()
