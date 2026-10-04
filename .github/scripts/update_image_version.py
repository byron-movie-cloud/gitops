import base64
import json
import os
import re
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import yaml


COMPONENTS = {"auth", "movie", "user", "frontend"}
IMAGE_TAG_PATTERN = re.compile(r"^[0-9a-f]{40}$")
VALUES_PATH = "values-production.yaml"
API_ROOT = "https://api.github.com"


def github_request(method, url, token, payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "movie-cloud-gitops-updater",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    component = os.environ["IMAGE_COMPONENT"]
    image_tag = os.environ["IMAGE_TAG"]
    repository = os.environ["TARGET_REPOSITORY"]
    branch = os.environ["TARGET_BRANCH"]
    token = os.environ["GH_TOKEN"]

    if component not in COMPONENTS:
        raise ValueError(f"Unsupported image component: {component}")
    if not IMAGE_TAG_PATTERN.fullmatch(image_tag):
        raise ValueError("Image tag must be a full 40-character commit SHA")

    api_path = quote(VALUES_PATH, safe="/")
    query = urlencode({"ref": branch})
    content_url = f"{API_ROOT}/repos/{repository}/contents/{api_path}?{query}"

    for attempt in range(5):
        current = github_request("GET", content_url, token)
        values = yaml.safe_load(base64.b64decode(current["content"]))
        image = values["services"][component]["image"]
        if image["tag"] == image_tag:
            print(f"{component} is already deployed at {image_tag}")
            return

        image["tag"] = image_tag
        updated = yaml.safe_dump(
            values,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        ).encode("utf-8")
        payload = {
            "message": f"chore(deploy): update {component} image to {image_tag[:12]}",
            "content": base64.b64encode(updated).decode("ascii"),
            "sha": current["sha"],
            "branch": branch,
        }

        try:
            github_request("PUT", content_url.split("?", 1)[0], token, payload)
            print(f"Updated {component} image tag to {image_tag}")
            return
        except HTTPError as error:
            if error.code not in (409, 422) or attempt == 4:
                raise
            time.sleep(1)


if __name__ == "__main__":
    main()
