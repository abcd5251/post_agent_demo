"""Buffer GraphQL API (https://developers.buffer.com)."""

import json
from datetime import timezone

import requests

from .common import env, log

API = "https://api.buffer.com"
CHANNEL_ENV = {"facebook": "BUFFER_FACEBOOK_CHANNEL_ID", "instagram": "BUFFER_INSTAGRAM_CHANNEL_ID"}


def _q(value):
    """Python str -> GraphQL string literal (JSON escaping is valid GraphQL)."""
    return json.dumps(value, ensure_ascii=False)


class Buffer:
    def __init__(self):
        self.key = env("BUFFER_API_KEY")
        self._channels = None

    def gql(self, query):
        resp = requests.post(API, json={"query": query}, timeout=60,
                             headers={"Authorization": f"Bearer {self.key}"})
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"Buffer HTTP {resp.status_code}: {resp.text[:300]}")
        if resp.status_code != 200 or data.get("errors"):
            raise RuntimeError(f"Buffer error (HTTP {resp.status_code}): {data.get('errors', data)}")
        return data["data"]

    def channels(self):
        """All channels across the account's organizations: [{"id", "name", "service"}]."""
        if self._channels is None:
            orgs = self.gql("query { account { organizations { id name } } }")["account"]["organizations"]
            self._channels = []
            for org in orgs:
                self._channels += self.gql(
                    f"query {{ channels(input: {{ organizationId: {_q(org['id'])} }}) "
                    f"{{ id name service }} }}")["channels"]
        return self._channels

    def channel_id(self, platform):
        override = env(CHANNEL_ENV[platform], required=False)
        if override:
            return override
        matches = [c for c in self.channels() if c["service"].lower() == platform]
        if len(matches) != 1:
            raise RuntimeError(
                f"found {len(matches)} {platform} channels in Buffer; set {CHANNEL_ENV[platform]} "
                f"(run `python main.py check` to list channel ids)")
        return matches[0]["id"]

    def schedule(self, platform, text, image_url, due):
        """Create a scheduled post; `due` is an aware datetime. Returns the Buffer post id."""
        due_at = due.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        metadata = ("metadata: { instagram: { type: post, shouldShareToFeed: true } }"
                    if platform == "instagram" else "")
        result = self.gql(f"""
        mutation {{
          createPost(input: {{
            text: {_q(text)}
            channelId: {_q(self.channel_id(platform))}
            schedulingType: automatic
            mode: customScheduled
            dueAt: {_q(due_at)}
            assets: [{{ image: {{ url: {_q(image_url)} }} }}]
            {metadata}
          }}) {{
            ... on PostActionSuccess {{ post {{ id dueAt }} }}
            ... on MutationError {{ message }}
          }}
        }}""")["createPost"]
        if "message" in result:
            raise RuntimeError(result["message"])
        log(f"Buffer {platform}: scheduled post {result['post']['id']} at {result['post']['dueAt']}")
        return result["post"]["id"]
