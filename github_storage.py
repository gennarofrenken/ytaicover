"""
GitHub Storage Module
Stores files in a GitHub repository using the GitHub API
Note: GitHub has 100MB file size limit and 100GB repository limit
"""

import os
import base64
import requests
from urllib.parse import quote

# GitHub Configuration - get from environment variables
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')  # Personal Access Token
GITHUB_REPO = os.environ.get('GITHUB_REPO', '')    # username/repo-name
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')
GITHUB_API_BASE = 'https://api.github.com/repos'

# Storage path within the repository
STORAGE_PATH = 'storage'  # All files stored in repo_root/storage/

# Enable/disable GitHub storage
USE_GITHUB = all([GITHUB_TOKEN, GITHUB_REPO])


def get_headers():
    """Get GitHub API headers with authentication"""
    return {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }


def get_file_sha(path):
    """Get the SHA of a file (needed for updates/deletes)"""
    if not USE_GITHUB:
        return None

    try:
        url = f'{GITHUB_API_BASE}/{GITHUB_REPO}/contents/{path}'
        response = requests.get(url, headers=get_headers(), params={'ref': GITHUB_BRANCH})

        if response.status_code == 200:
            return response.json().get('sha')
        return None

    except Exception as e:
        print(f'GitHub get SHA error: {e}')
        return None


def upload_to_github(file_path, repo_path):
    """Upload a file to GitHub repository

    Args:
        file_path: Local path to the file
        repo_path: Path within the repository (e.g., 'channel/beat/file.mp3')

    Returns:
        Public raw URL if successful, None otherwise
    """
    if not USE_GITHUB:
        print('GitHub storage not enabled')
        return None

    try:
        # Check if file exists
        if not os.path.exists(file_path):
            print(f'File not found: {file_path}')
            return None

        # Check file size BEFORE reading into memory (GitHub 100MB limit)
        file_size = os.path.getsize(file_path)
        if file_size > 100 * 1024 * 1024:  # 100MB
            print(f'File too large for GitHub: {file_size / 1024 / 1024:.1f}MB')
            return None

        # Read and encode file (only after size check)
        with open(file_path, 'rb') as f:
            content = base64.b64encode(f.read()).decode('utf-8')

        # Check if file already exists
        full_path = f'{STORAGE_PATH}/{repo_path}'
        sha = get_file_sha(full_path)

        # Prepare API request
        url = f'{GITHUB_API_BASE}/{GITHUB_REPO}/contents/{full_path}'
        data = {
            'message': f'Upload {repo_path}',
            'content': content,
            'branch': GITHUB_BRANCH
        }

        if sha:
            data['sha'] = sha
            data['message'] = f'Update {repo_path}'

        # Upload file
        response = requests.put(url, headers=get_headers(), json=data, timeout=30)

        if response.status_code in [200, 201]:
            # Return raw.githubusercontent.com URL
            return f'https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{full_path}'

        print(f'GitHub upload HTTP {response.status_code}: {response.text[:200]}')
        return None

    except Exception as e:
        print(f'GitHub upload exception: {type(e).__name__}: {str(e)}')
        return None


def download_from_github(repo_path, local_path):
    """Download a file from GitHub repository

    Args:
        repo_path: Path within the repository (e.g., 'channel/beat/file.mp3')
        local_path: Local path to save the file

    Returns:
        True if successful, False otherwise
    """
    if not USE_GITHUB:
        return False

    try:
        full_path = f'{STORAGE_PATH}/{repo_path}'
        url = f'{GITHUB_API_BASE}/{GITHUB_REPO}/contents/{full_path}'
        response = requests.get(url, headers=get_headers(), params={'ref': GITHUB_BRANCH})

        if response.status_code == 200:
            data = response.json()
            content = base64.b64decode(data['content'])

            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'wb') as f:
                f.write(content)
            return True

        return False

    except Exception as e:
        print(f'GitHub download error: {e}')
        return False


def file_exists_in_github(repo_path):
    """Check if a file exists in GitHub

    Args:
        repo_path: Path within the repository

    Returns:
        True if exists, False otherwise
    """
    return get_file_sha(f'{STORAGE_PATH}/{repo_path}') is not None


def delete_from_github(repo_path):
    """Delete a file from GitHub repository

    Args:
        repo_path: Path within the repository

    Returns:
        True if successful, False otherwise
    """
    if not USE_GITHUB:
        return False

    try:
        full_path = f'{STORAGE_PATH}/{repo_path}'
        sha = get_file_sha(full_path)

        if not sha:
            return False  # File doesn't exist

        url = f'{GITHUB_API_BASE}/{GITHUB_REPO}/contents/{full_path}'
        data = {
            'message': f'Delete {repo_path}',
            'sha': sha,
            'branch': GITHUB_BRANCH
        }

        response = requests.delete(url, headers=get_headers(), json=data)
        return response.status_code == 200

    except Exception as e:
        print(f'GitHub delete error: {e}')
        return False


def list_github_files(prefix=''):
    """List files in GitHub with given prefix (recursively)

    Args:
        prefix: Path prefix to filter

    Returns:
        List of file info dicts with 'name', 'path', 'size', 'url'
    """
    if not USE_GITHUB:
        return []

    try:
        full_prefix = f'{STORAGE_PATH}/{prefix}' if prefix else STORAGE_PATH
        url = f'{GITHUB_API_BASE}/{GITHUB_REPO}/contents/{full_prefix}'
        response = requests.get(url, headers=get_headers(), params={'ref': GITHUB_BRANCH})

        if response.status_code == 200:
            files = []
            items = response.json()

            # Handle both list of items and single item responses
            if not isinstance(items, list):
                items = [items] if items else []

            def process_item(item, current_prefix=''):
                """Recursively process items to find all files"""
                if item['type'] == 'file':
                    # Remove STORAGE_PATH prefix from the path
                    relative_path = item['path'][len(STORAGE_PATH)+1:]
                    files.append({
                        'name': item['name'],
                        'path': relative_path,
                        'size': item['size'],
                        'url': item['download_url']
                    })
                elif item['type'] == 'dir':
                    # Recursively fetch files from subdirectory
                    dir_url = f'{GITHUB_API_BASE}/{GITHUB_REPO}/contents/{item["path"]}'
                    dir_response = requests.get(dir_url, headers=get_headers(), params={'ref': GITHUB_BRANCH})
                    if dir_response.status_code == 200:
                        sub_items = dir_response.json()
                        if not isinstance(sub_items, list):
                            sub_items = [sub_items] if sub_items else []
                        for sub_item in sub_items:
                            process_item(sub_item, current_prefix + item['name'] + '/')

            for item in items:
                process_item(item)

            return files

        return []

    except Exception as e:
        print(f'GitHub list error: {e}')
        return []


def get_repo_size():
    """Get approximate repository size in MB

    Returns:
        Size in MB or None if unavailable
    """
    if not USE_GITHUB:
        return None

    try:
        url = f'{GITHUB_API_BASE}/{GITHUB_REPO}'
        response = requests.get(url, headers=get_headers())

        if response.status_code == 200:
            return response.json().get('size')  # Size in KB

        return None

    except Exception as e:
        print(f'GitHub repo size error: {e}')
        return None
