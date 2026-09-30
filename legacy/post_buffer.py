"""Schedule assets/text.txt + assets/image.png to Instagram and Facebook via Buffer.

Buffer does the scheduling: this script creates the posts in Buffer with
dueAt = config.POST_TIME and exits. Buffer publishes them at that time, so no
server has to stay running. Uses the same config.py as post.py.

Buffer needs a public image URL, so the image is uploaded to Cloudinary first
(padded to 4:5 JPEG, which works for both IG and FB).

Usage:
    python post_buffer.py                  # schedule at config.POST_TIME
    python post_buffer.py --now            # schedule ~2 minutes from now
    python post_buffer.py --list-channels  # show Buffer channels and their ids
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import requests

import config
import post
from post import POST_TIME, env, log

BUFFER_API = "https://api.buffer.com"


def gql(query):
    resp = requests.post(
        BUFFER_API,
        json={"query": query},
        headers={"Authorization": f"Bearer {env('BUFFER_API_KEY')}"},
        timeout=60,
    )
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"Buffer API HTTP {resp.status_code}: {resp.text[:300]}")
    if resp.status_code != 200 or data.get("errors"):
        raise RuntimeError(f"Buffer API error (HTTP {resp.status_code}): {data.get('errors', data)}")
    return data["data"]


def s(value):
    """Quote a Python string as a GraphQL string literal (JSON escaping is valid GraphQL)."""
    return json.dumps(value, ensure_ascii=False)


def get_channels():
    orgs = gql("query { account { organizations { id name } } }")["account"]["organizations"]
    channels = []
    for org in orgs:
        found = gql(f"query {{ channels(input: {{ organizationId: {s(org['id'])} }}) "
                    f"{{ id name service }} }}")["channels"]
        channels += [{**c, "organization": org["name"]} for c in found]
    return channels


def pick_channel(channels, service, override_env):
    override = env(override_env, required=False)
    if override:
        return override
    matches = [c for c in channels if c["service"].lower() == service]
    if len(matches) != 1:
        sys.exit(f"[error] found {len(matches)} {service} channels in Buffer; set {override_env} "
                 f"in .env (run `python post_buffer.py --list-channels` to see ids)")
    log(f"{service} channel: {matches[0]['name']} ({matches[0]['id']})")
    return matches[0]["id"]


def create_post(channel_id, caption, image_url, due_at, instagram=False):
    metadata = "metadata: { instagram: { type: post, shouldShareToFeed: true } }" if instagram else ""
    data = gql(f"""
    mutation {{
      createPost(input: {{
        text: {s(caption)}
        channelId: {s(channel_id)}
        schedulingType: automatic
        mode: customScheduled
        dueAt: {s(due_at)}
        assets: [{{ image: {{ url: {s(image_url)} }} }}]
        {metadata}
      }}) {{
        ... on PostActionSuccess {{ post {{ id dueAt }} }}
        ... on MutationError {{ message }}
      }}
    }}""")["createPost"]
    if "message" in data:
        raise RuntimeError(data["message"])
    return data["post"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", action="store_true", help="schedule ~2 minutes from now")
    parser.add_argument("--list-channels", action="store_true", help="list Buffer channels")
    args = parser.parse_args()

    if args.list_channels:
        for c in get_channels():
            print(f"{c['service']:<12} {c['id']}  {c['name']}  (org: {c['organization']})")
        return

    due = datetime.now(timezone.utc) + timedelta(minutes=2) if args.now else POST_TIME
    if due <= datetime.now(timezone.utc):
        sys.exit(f"[error] POST_TIME {config.POST_TIME} ({config.TIMEZONE}) is in the past; "
                 f"update config.py or use --now")
    due_at = due.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    caption, image_path = post.load_assets()
    log(f"caption ({len(caption)} chars):\n{caption}")

    channels = get_channels()
    targets = []
    if config.POST_TO_INSTAGRAM:
        targets.append(("Instagram", pick_channel(channels, "instagram", "BUFFER_INSTAGRAM_CHANNEL_ID"), True))
    if config.POST_TO_FACEBOOK:
        targets.append(("Facebook", pick_channel(channels, "facebook", "BUFFER_FACEBOOK_CHANNEL_ID"), False))

    image_url = post.upload_to_cloudinary(image_path)

    failures = []
    for name, channel_id, is_instagram in targets:
        try:
            created = create_post(channel_id, caption, image_url, due_at, instagram=is_instagram)
            log(f"{name}: scheduled in Buffer, post id={created['id']}, dueAt={created['dueAt']}")
        except Exception as e:
            failures.append(f"{name}: {e}")
            log(f"[error] {name}: {e}")
    if failures:
        sys.exit(1)
    log(f"done. Buffer will publish at {due.astimezone(post.TZ):%Y-%m-%d %H:%M} ({config.TIMEZONE}).")


if __name__ == "__main__":
    main()
