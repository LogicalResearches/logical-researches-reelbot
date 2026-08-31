from pathlib import Path

from reelbot.config import load_config
from reelbot.instagram import InstagramPublisher


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, data, timeout):
        self.posts.append((url, data))
        if url.endswith("/media_publish"):
            return FakeResponse({"id": "media-456"})
        return FakeResponse({"id": "container-123"})

    def get(self, url, params, timeout):
        if url.endswith("container-123"):
            return FakeResponse({"status_code": "FINISHED"})
        return FakeResponse({"permalink": "https://www.instagram.com/reel/example/"})


def test_publish_uses_official_container_flow(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_USER_ID", "17890000000000000")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "secret-token")
    config = load_config(ROOT / "config.yaml")
    session = FakeSession()
    result = InstagramPublisher(config, session=session).publish(
        "https://example.org/reels/sample.mp4", "A concise caption"
    )
    assert result.container_id == "container-123"
    assert result.media_id == "media-456"
    assert result.permalink.endswith("/example/")
    assert session.posts[0][1]["media_type"] == "REELS"

