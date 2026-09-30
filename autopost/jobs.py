"""The two daily jobs and the time gate that decides whether a cron tick should run them."""

from datetime import timedelta

from openai import OpenAI

import config
from . import content, research
from .common import at_time, env, log, now, parse_post_time, post_time_for

STYLES = [config.COPY_STYLE_1, config.COPY_STYLE_2, config.COPY_STYLE_3]
RUN_TIMES = {"generate": config.GENERATE_TIME, "publish": config.PUBLISH_TIME}


def should_run(sheet, task):
    """True if it's past today's run time, today hasn't succeeded yet, and attempts remain."""
    current = now()
    today = current.date().isoformat()
    run_at = at_time(current.date(), RUN_TIMES[task])
    if current < run_at:
        log(f"{task}: scheduled for {RUN_TIMES[task]}, not yet.")
        return False
    state = sheet.get_state(task)
    if state["last_success_date"] == today:
        log(f"{task}: already ran today.")
        return False
    attempts = int(state["attempts"] or 0) if state["attempt_date"] == today else 0
    if attempts >= config.MAX_ATTEMPTS_PER_DAY:
        log(f"{task}: failed {attempts} times today, giving up until tomorrow. "
            f"Last error: {state['message']}")
        return False
    return True


def run_task(sheet, task, job, force=False):
    """Run job(sheet) with the time gate and record the outcome in the state tab."""
    if not force and not should_run(sheet, task):
        return True
    current = now()
    today = current.date().isoformat()
    state = sheet.get_state(task)
    attempts = (int(state["attempts"] or 0) if state["attempt_date"] == today else 0) + 1
    sheet.set_state(task, {"attempt_date": today, "attempts": str(attempts),
                           "last_run_at": f"{current:%Y-%m-%d %H:%M:%S}", "message": "running"})
    try:
        message = job(sheet)
    except Exception as e:
        log(f"[error] {task} failed: {e}")
        sheet.set_state(task, {"message": f"ERROR: {e}"[:500]})
        return False
    sheet.set_state(task, {"last_success_date": today, "message": message[:500]})
    log(f"{task}: {message}")
    return True


# ── generate ────────────────────────────────────────────────

def build_posts():
    """Research + write 3 copies + 3 images. Returns (posts, errors); no sheet access."""
    client = OpenAI(api_key=env("OPENAI_API_KEY"))
    notes, web_sources = research.web_search(client)
    rss_items = research.fetch_rss()
    rss_text = research.format_rss(rss_items)
    sources = "\n".join(dict.fromkeys(
        [s["url"] for s in web_sources] + [i["url"] for i in rss_items[:5]]))

    today = now().date()
    posts, errors = [], []
    for n, style in enumerate(STYLES, start=1):
        try:
            log(f"writing copy {n}/{len(STYLES)}: {style['name']}")
            copy = content.write_copy(client, style, notes, rss_text)
            image_prompt = content.make_image_prompt(client, style, copy)
            log(f"generating image {n}/{len(STYLES)}")
            png = content.generate_image(client, image_prompt)
            post_id = f"{today.isoformat()}-{n}"
            image_url = content.upload_image(png, post_id)
        except Exception as e:
            errors.append(f"{style['name']}: {e}")
            log(f"[error] copy {n} ({style['name']}) failed: {e}")
            continue
        posts.append({
            "id": post_id,
            "created_at": f"{now():%Y-%m-%d %H:%M}",
            "keywords": ", ".join(config.KEYWORDS),
            "version": style["name"],
            "copy": copy,
            "image_url": image_url,
            "image_prompt": image_prompt,
            "sources": sources,
            "post_time": post_time_for(style, today),
            "status": "PENDING",
        })
    return posts, errors


def generate_job(sheet):
    posts, errors = build_posts()
    if not posts:
        raise RuntimeError("no copy generated: " + "; ".join(errors))
    start, end = sheet.append_posts(posts)
    message = f"added {len(posts)} rows ({start}-{end})"
    if errors:
        message += " | failed: " + "; ".join(errors)
    return message


# ── publish ─────────────────────────────────────────────────

def is_checked(value):
    return value is True or str(value).strip().upper() in ("TRUE", "1", "YES", "V", "✓", "☑")


def publish_job(sheet, buffer, dry_run=False):
    """Schedule every approved, not-yet-scheduled row on Buffer at its post_time."""
    scheduled, failed, skipped = 0, 0, 0
    earliest = now() + timedelta(minutes=config.MIN_LEAD_MINUTES)
    for row_number, row in sheet.list_posts():
        # Only APPROVED rows: PENDING rows without the checkbox are never published.
        if not is_checked(row["approved"]) or row["status"] == "SCHEDULED":
            continue
        label = f"row {row_number} ({row['id']} {row['version']})"
        try:
            due = parse_post_time(row["post_time"])
        except ValueError as e:
            sheet.update_post(row_number, {"error": str(e)})
            log(f"[error] {label}: {e}")
            failed += 1
            continue
        if due < earliest:
            msg = f"post_time {row['post_time']} 已過或太接近現在，請改成未來時間，下次排程會再試"
            sheet.update_post(row_number, {"error": msg})
            log(f"[skip] {label}: {msg}")
            skipped += 1
            continue
        if not row["copy"] or not row["image_url"]:
            sheet.update_post(row_number, {"error": "copy 或 image_url 是空的"})
            failed += 1
            continue

        errors = []
        for platform in config.PUBLISH_PLATFORMS:
            column = f"buffer_{platform}_id"
            if row.get(column):
                continue  # already scheduled on an earlier run; don't post twice
            if dry_run:
                log(f"[dry-run] {label}: would schedule {platform} at {due:%Y-%m-%d %H:%M}")
                continue
            try:
                post_id = buffer.schedule(platform, row["copy"], row["image_url"], due)
                sheet.update_post(row_number, {column: post_id})  # save right away
                row[column] = post_id
            except Exception as e:
                errors.append(f"{platform}: {e}")
                log(f"[error] {label} {platform}: {e}")

        if dry_run:
            continue
        if errors:
            # Keep the row as-is (not SCHEDULED) so the next run retries the failed platform.
            sheet.update_post(row_number, {"error": "; ".join(errors)[:500]})
            failed += 1
        else:
            sheet.update_post(row_number, {"status": "SCHEDULED", "error": "",
                                           "scheduled_at": f"{now():%Y-%m-%d %H:%M}"})
            scheduled += 1

    message = f"scheduled {scheduled}, failed {failed}, skipped {skipped}"
    if failed:
        # Let run_task record a failure so it's retried (up to MAX_ATTEMPTS_PER_DAY).
        raise RuntimeError(message)
    return message
