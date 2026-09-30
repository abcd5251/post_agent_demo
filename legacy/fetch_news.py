"""Every FETCH_INTERVAL_SECONDS, search the latest news on config_openai.TOPIC,
and save the summary + a generated image to assets/<date-time>/text.txt and image.png.

Settings are in config_openai.py. Stop with Ctrl+C.

Usage:
    python fetch_news.py            # run on the configured interval
    python fetch_news.py --once     # fetch once and exit
"""

import argparse
import time
from datetime import datetime

import config_openai as cfg
from post import BASE_DIR, log
from post_openai import TZ, generate_content


def fetch_once():
    folder = BASE_DIR / cfg.FETCH_OUTPUT_DIR / datetime.now(TZ).strftime(cfg.FETCH_FOLDER_FORMAT)
    caption, _ = generate_content(image_path=folder / "image.png")
    (folder / "text.txt").write_text(caption + "\n", encoding="utf-8")
    log(f"saved {folder}/text.txt + image.png")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="fetch once and exit")
    args = parser.parse_args()

    max_runs = 1 if args.once else cfg.FETCH_MAX_RUNS
    runs = 0
    try:
        while max_runs is None or runs < max_runs:
            started = time.monotonic()
            runs += 1
            try:
                fetch_once()
            except Exception as e:
                # One failed fetch (network, rate limit...) shouldn't stop the loop.
                log(f"[error] fetch #{runs} failed: {e}")
            if max_runs is not None and runs >= max_runs:
                break
            wait = cfg.FETCH_INTERVAL_SECONDS - (time.monotonic() - started)
            if wait > 0:
                log(f"next fetch in {wait:.0f}s")
                time.sleep(wait)
    except KeyboardInterrupt:
        log("stopped.")


if __name__ == "__main__":
    main()
