"""Entry point for the Render cron jobs and for local debugging.

    python main.py generate            # cron: runs if it's past GENERATE_TIME and not done today
    python main.py publish             # cron: runs if it's past PUBLISH_TIME and not done today
    python main.py generate --force    # run now, ignore the schedule
    python main.py publish --force
    python main.py generate --dry-run  # generate copies + images, print them, don't touch the sheet
    python main.py publish --dry-run   # show what would be scheduled, don't call Buffer
    python main.py check               # verify env vars, Google Sheet, Buffer channels, OpenAI key
"""

import argparse
import sys

import config
from autopost.common import ConfigError, env, log


def cmd_generate(args):
    from autopost import jobs
    if args.dry_run:
        posts, errors = jobs.build_posts()
        for p in posts:
            print(f"\n===== {p['version']}  (post_time {p['post_time']}) =====\n{p['copy']}\n"
                  f"image: {p['image_url']}\nprompt: {p['image_prompt']}")
        print(f"\nsources:\n{posts[0]['sources'] if posts else ''}")
        return not errors
    from autopost.sheet import Sheet
    return jobs.run_task(Sheet(), "generate", jobs.generate_job, force=args.force)


def cmd_publish(args):
    from autopost import jobs
    from autopost.buffer import Buffer
    from autopost.sheet import Sheet
    sheet = Sheet()
    buffer = None if args.dry_run else Buffer()
    if args.dry_run:
        jobs.publish_job(sheet, buffer, dry_run=True)
        return True
    return jobs.run_task(sheet, "publish", lambda s: jobs.publish_job(s, buffer), force=args.force)


def cmd_check(args):
    ok = True
    for name in ["OPENAI_API_KEY", "GOOGLE_SHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON",
                 "BUFFER_API_KEY", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY",
                 "CLOUDINARY_API_SECRET"]:
        present = bool(env(name, required=False))
        ok &= present
        print(f"{'OK ' if present else 'MISSING'}  {name}")

    checks = []

    def openai_check():
        from openai import OpenAI
        OpenAI(api_key=env("OPENAI_API_KEY")).models.retrieve(config.TEXT_MODEL)
        return f"model {config.TEXT_MODEL} available"

    def sheet_check():
        from autopost.sheet import Sheet
        sheet = Sheet()
        return f"'{sheet.book.title}': {len(sheet.list_posts())} rows in tab '{config.SHEET_TAB}'"

    def buffer_check():
        from autopost.buffer import Buffer
        buffer = Buffer()
        lines = [f"{c['service']:<10} {c['id']}  {c['name']}" for c in buffer.channels()]
        for platform in config.PUBLISH_PLATFORMS:
            lines.append(f"-> {platform} uses channel {buffer.channel_id(platform)}")
        return "\n    ".join(lines)

    def cloudinary_check():
        import cloudinary
        import cloudinary.api
        cloudinary.config(cloud_name=env("CLOUDINARY_CLOUD_NAME"),
                          api_key=env("CLOUDINARY_API_KEY"),
                          api_secret=env("CLOUDINARY_API_SECRET"))
        return cloudinary.api.ping()["status"]

    for name, fn in [("OpenAI", openai_check), ("Google Sheet", sheet_check),
                     ("Buffer", buffer_check), ("Cloudinary", cloudinary_check)]:
        try:
            print(f"OK       {name}: {fn()}")
        except Exception as e:
            ok = False
            print(f"FAILED   {name}: {e}")
    return ok


def main():
    parser = argparse.ArgumentParser(description="AI news -> marketing copy -> Buffer")
    parser.add_argument("command", choices=["generate", "publish", "check"])
    parser.add_argument("--force", action="store_true", help="run now, ignore the schedule")
    parser.add_argument("--dry-run", action="store_true", help="don't write to sheet / Buffer")
    args = parser.parse_args()
    try:
        ok = {"generate": cmd_generate, "publish": cmd_publish, "check": cmd_check}[args.command](args)
    except ConfigError as e:
        log(f"[error] {e}")
        ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
