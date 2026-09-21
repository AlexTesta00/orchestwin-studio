import base64
import io
import zipfile
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings


def test_source_preview_is_authenticated_json_and_zip_never_application_html():
    owner, project, revision = uuid4(), uuid4(), uuid4()
    calls = []

    async def source_files(**scope):
        calls.append(scope)
        if scope["project_id"] != project or scope["revision_id"] != revision:
            return None
        return (
            {"target_selection": {"target": "WEB_STATIC"}, "content_hash": "a" * 64},
            [("index.html", "text/html", b"<script>console.log(1)</script>")],
        )

    runtime = ApplicationRuntime(web_source_api_service=SimpleNamespace(source_files=source_files))
    app = create_app(ApplicationSettings(_env_file=None), runtime=runtime)
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=owner)
    with TestClient(app) as client:
        path = f"/api/v1/projects/{project}/web-source-revisions/{revision}"
        response = client.get(path + "/content")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.headers["cache-control"] == "no-store"
        assert base64.b64decode(response.json()["files"][0]["base64"]).startswith(b"<script>")
        downloaded = client.get(path + "/download")
        assert downloaded.headers["content-disposition"].startswith("attachment;")
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
            assert archive.namelist() == ["index.html"]
        assert client.get(path.replace(str(project), str(uuid4())) + "/content").status_code == 404
        assert all(call["owner_user_id"] == owner for call in calls)
        app.dependency_overrides.clear()
        assert client.get(path + "/content").status_code in (401, 503)
