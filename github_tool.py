# ----------------------------------------------------------------------
# File: github_tool.py (Updated with Release Analysis)
# Description: Contains the GitHub API functions for the Gemini Agent.
# ----------------------------------------------------------------------
import os
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional

# --- Tool 1: Check Latest Release (Existing) ---

def _get_auth_headers() -> Dict[str, str]:
    """Internal helper to create headers with the GitHub token."""
    github_token = os.getenv("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    return headers

def _make_api_call(url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
    """Internal helper for API calls with basic error handling."""
    return requests.get(url, headers=headers, params=params)

def check_latest_release(org_name: str, repo_name: str) -> str:
    """
    Checks the latest stable release version, publish date, and the direct
    GitHub release URL for a public repository (e.g., hashicorp/vault).
    """
    api_url = f"https://api.github.com/repos/{org_name}/{repo_name}/releases/latest"
    headers = _get_auth_headers()

    try:
        response = _make_api_call(api_url, headers)

        if response.status_code == 404:
            return f"ERROR: Repository {org_name}/{repo_name} not found or has no releases."
        if response.status_code == 403:
            return f"ERROR: GitHub API failed with status code 403. Check GITHUB_TOKEN and rate limit."
        if response.status_code != 200:
            return f"ERROR: GitHub API failed with status code {response.status_code}."

        data = response.json()

        version = data.get('tag_name', 'N/A')
        published_at_str = data.get('published_at', 'N/A')
        release_url = data.get('html_url', 'N/A')

        published_date = 'N/A'
        if published_at_str != 'N/A':
            published_at = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
            published_date = published_at.strftime("%Y-%m-%d")

        body_snippet = data.get('body', '')[:100].replace('\n', ' ') + '...'

        return (
            f"SUCCESS: **{org_name}/{repo_name}** Latest Release: **{version}** | "
            f"Published: {published_date}. "
            f"Release URL: {release_url}. "
            f"Notes Snippet: \"{body_snippet}\""
        )
    except requests.exceptions.RequestException as e:
        return f"TOOL_ERROR: Network or connection issue: {str(e)}"

# --- Tool 2: Get Dependency File Content (Existing) ---

def get_dependency_file(org_name: str, repo_name: str, file_path: str) -> str:
    """
    Fetches the content of a specified dependency file (e.g., go.mod, package.json)
    from a public GitHub repository and returns the first 10 lines.
    """
    api_url = f"https://api.github.com/repos/{org_name}/{repo_name}/contents/{file_path}"
    
    # We need the 'raw' Accept header for direct file content
    headers = {"Accept": "application/vnd.github.v3.raw"}
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    try:
        response = _make_api_call(api_url, headers)

        if response.status_code == 404:
            return f"ERROR: File '{file_path}' not found in {org_name}/{repo_name}."
        if response.status_code == 403:
            return f"ERROR: GitHub API failed with status code 403. Check GITHUB_TOKEN and rate limit."
        if response.status_code != 200:
            return f"ERROR: GitHub API failed with status code {response.status_code}."

        content_text = response.text
        lines = content_text.split('\n')
        snippet = '\n'.join(lines[:10])

        return f"SUCCESS: Content of `{file_path}`:\n```\n{snippet}\n```"

    except Exception as e:
        return f"TOOL_ERROR: Could not process file content. Error: {str(e)}"

# ----------------------------------------------------------------------
# --- Tool 3: Get Release Pull Requests (NEW) ---
# ----------------------------------------------------------------------

def _fetch_merged_prs(org_name: str, repo_name: str, published_date: str) -> List[Dict[str, Any]]:
    """Helper to fetch recently merged PRs before a given published date."""
    
    # We query for closed/merged PRs, sorted by most recent update
    api_url = f"https://api.github.com/repos/{org_name}/{repo_name}/issues"
    headers = _get_auth_headers()
    
    # We fetch closed issues (which includes PRs) updated after a relevant time
    # A robust solution needs tag commit comparison, but we simplify with a time filter
    params = {
        "state": "closed",
        "sort": "updated",
        "direction": "desc",
        "since": published_date, # Only PRs updated since the release date (as a proxy)
        "per_page": 50
    }
    
    response = _make_api_call(api_url, headers, params=params)
    if response.status_code != 200:
        return []

    all_closed_items = response.json()
    
    prs = []
    for item in all_closed_items:
        # Check if it's a Pull Request AND if it has a merged_at date
        if 'pull_request' in item and item.get("pull_request", {}).get("merged_at"):
            prs.append({
                "number": item['number'],
                "title": item['title'],
                "labels": [label['name'] for label in item.get('labels', [])],
                "url": item['html_url'],
            })
            
    return prs

def get_release_prs(org_name: str, repo_name: str, tag_name: str) -> str:
    """
    Analyzes merged Pull Requests that were included in a specific release tag
    and categorizes them into Bug Fixes, Enhancements, and Other Changes based
    on labels and Conventional Commit prefixes (fix:, feat:).
    """
    
    # 1. Get the release date to narrow the PR search
    release_url = f"https://api.github.com/repos/{org_name}/{repo_name}/releases/tags/{tag_name}"
    release_response = _make_api_call(release_url, _get_auth_headers())
    
    if release_response.status_code != 200:
        return f"ERROR: Could not find release tag `{tag_name}` for categorization. Status: {release_response.status_code}."
        
    release_data = release_response.json()
    published_date_str = release_data.get('published_at', datetime.now().isoformat())
    
    # 2. Fetch relevant PRs
    try:
        # Note: We use the published date of the *previous* release or a relevant window
        # For simplicity here, we fetch all PRs updated *since* the target release date
        # (This is an imperfect proxy, but allows the model to categorize the most recent work)
        all_prs = _fetch_merged_prs(org_name, repo_name, published_date_str)
    except Exception as e:
        return f"TOOL_ERROR: Failed to fetch PRs for release. Error: {str(e)}"

    if not all_prs:
        return f"SUCCESS: Found no recently merged Pull Requests for release `{tag_name}`."

    # 3. Categorize Changes
    summary = {
        "Bug Fixes": [],
        "Enhancements/Features": [],
        "Other Changes": []
    }

    BUG_KEYWORDS = ["bug", "fix", "defect", "hotfix"]
    ENHANCEMENT_KEYWORDS = ["feature", "enhancement", "new", "feat"]

    for pr in all_prs:
        title_lower = pr['title'].lower()
        labels_lower = [label.lower() for label in pr['labels']]
        
        if any(kw in labels_lower for kw in BUG_KEYWORDS) or title_lower.startswith('fix'):
            summary["Bug Fixes"].append(f"#{pr['number']}: {pr['title']}")
        elif any(kw in labels_lower for kw in ENHANCEMENT_KEYWORDS) or title_lower.startswith('feat'):
            summary["Enhancements/Features"].append(f"#{pr['number']}: {pr['title']}")
        else:
            summary["Other Changes"].append(f"#{pr['number']}: {pr['title']}")

    # 4. Format Output for LLM
    output_parts = [
        f"SUCCESS: Analysis for {org_name}/{repo_name} release `{tag_name}`:",
        f"Total Relevant PRs Found: {len(all_prs)}"
    ]
    
    for category, items in summary.items():
        if items:
            output_parts.append(f"\n--- {category} ({len(items)}) ---")
            output_parts.extend(items)
            
    return '\n'.join(output_parts)


# --- Tool 4: Check GitHub API Health (NEW) ---
import requests
from datetime import datetime # <--- MAKE SURE datetime IS IMPORTED AT THE TOP
from typing import Dict, Any, List, Optional
# ... (Keep existing code from Tool 1, 2, and 3)

# ----------------------------------------------------------------------
# --- Tool 4: Check GitHub API Health (NEW) ---
# ----------------------------------------------------------------------

def check_github_api_health() -> Dict[str, Any]:
    """
    Checks the remaining rate limit for the GitHub token currently in use.
    Returns the limit, remaining calls, and the reset time.
    """
    api_url = "https://api.github.com/rate_limit"
    headers = _get_auth_headers() # Uses the existing helper to get the token

    try:
        response = requests.get(api_url, headers=headers)
        
        if response.status_code != 200:
            return {
                "status": "ERROR",
                "message": f"Could not check rate limit. Status: {response.status_code}",
                "remaining": 0
            }

        data = response.json()
        rate_data = data.get('resources', {}).get('core', {})
        
        limit = rate_data.get('limit', 'N/A')
        remaining = rate_data.get('remaining', 'N/A')
        reset_ts = rate_data.get('reset', 'N/A')
        
        reset_time = 'N/A'
        if isinstance(reset_ts, int):
            # Convert Unix timestamp to human-readable time
            reset_time = datetime.fromtimestamp(reset_ts).strftime("%Y-%m-%d %H:%M:%S")

        return {
            "status": "SUCCESS",
            "limit": limit,
            "remaining": remaining,
            "reset_time": reset_time,
            "used_token": bool(os.getenv("GITHUB_TOKEN"))
        }

    except requests.exceptions.RequestException as e:
        return {
            "status": "TOOL_ERROR",
            "message": f"Network error during health check: {str(e)}",
            "remaining": 0
        }
