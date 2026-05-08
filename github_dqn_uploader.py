
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _read_local_secrets_file():
    """
    로컬 테스트용 .streamlit/secrets.toml을 읽는다.
    GitHub에는 절대 올리지 말아야 한다.
    """
    secrets_path = Path(".streamlit") / "secrets.toml"

    if not secrets_path.exists():
        return {}

    try:
        import tomllib

        with open(secrets_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _get_secret(name, default=None):
    """
    값 읽는 우선순위:
    1. Streamlit Cloud Secrets
    2. 환경변수
    3. 로컬 .streamlit/secrets.toml
    """
    # 1) Streamlit secrets
    try:
        import streamlit as st

        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass

    # 2) Environment variable
    env_value = os.environ.get(name)

    if env_value is not None:
        return env_value

    # 3) Local secrets.toml
    local_secrets = _read_local_secrets_file()

    if name in local_secrets:
        return local_secrets[name]

    return default


def is_github_upload_configured():
    token = _get_secret("GITHUB_TOKEN")
    repo = _get_secret("GITHUB_REPO")

    return bool(token and repo)


def _github_api_request(method, url, token, payload=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "VARO-DQN-Uploader",
    }

    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)

    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def _get_existing_sha(owner_repo, github_path, branch, token):
    encoded_path = urllib.parse.quote(github_path)
    url = f"https://api.github.com/repos/{owner_repo}/contents/{encoded_path}?ref={urllib.parse.quote(branch)}"

    try:
        result = _github_api_request("GET", url, token)
        return result.get("sha")
    except urllib.error.HTTPError as e:
        # 404이면 아직 파일이 없는 것이므로 새로 만들면 된다.
        if e.code == 404:
            return None
        raise


def upload_file_to_github(
    local_file,
    github_path,
    repo=None,
    branch=None,
    token=None,
    commit_message=None,
):
    local_path = Path(local_file)

    if not local_path.exists():
        return {
            "ok": False,
            "file": str(local_path),
            "github_path": github_path,
            "message": "local file not found",
        }

    token = token or _get_secret("GITHUB_TOKEN")
    repo = repo or _get_secret("GITHUB_REPO")
    branch = branch or _get_secret("GITHUB_BRANCH", "main")

    if not token or not repo:
        return {
            "ok": False,
            "file": str(local_path),
            "github_path": github_path,
            "message": "GitHub token/repo not configured",
        }

    try:
        sha = _get_existing_sha(repo, github_path, branch, token)

        encoded_path = urllib.parse.quote(github_path)
        url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}"

        content = base64.b64encode(local_path.read_bytes()).decode("utf-8")

        payload = {
            "message": commit_message or f"Save DQN artifact {github_path}",
            "content": content,
            "branch": branch,
        }

        if sha:
            payload["sha"] = sha

        result = _github_api_request("PUT", url, token, payload)

        return {
            "ok": True,
            "file": str(local_path),
            "github_path": github_path,
            "sha": result.get("content", {}).get("sha"),
            "html_url": result.get("content", {}).get("html_url"),
            "message": "uploaded",
        }

    except urllib.error.HTTPError as e:
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            error_body = str(e)

        return {
            "ok": False,
            "file": str(local_path),
            "github_path": github_path,
            "message": f"GitHub HTTP error {e.code}: {error_body}",
        }

    except Exception as e:
        return {
            "ok": False,
            "file": str(local_path),
            "github_path": github_path,
            "message": str(e),
        }


def upload_dqn_artifacts_to_github(saved_paths, github_dir=None, commit_message=None):
    """
    DQN 학습 결과 파일을 GitHub 저장소에 자동 업로드한다.

    기본 저장 위치:
    dqn_artifacts/dqn_latest_model.npz
    dqn_artifacts/dqn_latest_recommendations.csv
    dqn_artifacts/dqn_latest_history.csv
    dqn_artifacts/dqn_latest_summary.json

    타임스탬프 백업 파일은 DQN_GITHUB_UPLOAD_TIMESTAMPED=true일 때만 업로드한다.
    """
    github_dir = github_dir or _get_secret("DQN_GITHUB_DIR", "dqn_artifacts")
    upload_timestamped = str(_get_secret("DQN_GITHUB_UPLOAD_TIMESTAMPED", "false")).lower() in [
        "1",
        "true",
        "yes",
        "y",
    ]

    latest_keys = [
        "model_file",
        "compare_file",
        "history_file",
        "summary_file",
    ]

    timestamp_keys = [
        "timestamp_model_file",
        "timestamp_compare_file",
        "timestamp_history_file",
        "timestamp_summary_file",
    ]

    keys_to_upload = list(latest_keys)

    if upload_timestamped:
        keys_to_upload.extend(timestamp_keys)

    results = []

    for key in keys_to_upload:
        local_path = saved_paths.get(key)

        if not local_path:
            continue

        local_file = Path(local_path)
        github_path = f"{github_dir}/{local_file.name}"

        results.append(
            upload_file_to_github(
                local_file=local_file,
                github_path=github_path,
                commit_message=commit_message or f"Save DQN training artifact: {local_file.name}",
            )
        )

    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = len(results) - ok_count

    return {
        "configured": is_github_upload_configured(),
        "github_dir": github_dir,
        "ok_count": ok_count,
        "fail_count": fail_count,
        "results": results,
    }
