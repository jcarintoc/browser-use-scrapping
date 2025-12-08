"""
HAR parsing, chunking, and summarization utilities.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlparse, parse_qs
import re
from collections import defaultdict


# ============================================================================
# HAR LOADING AND VALIDATION
# ============================================================================

def load_har_file(har_path: Path) -> dict:
    """
    Load HAR file from disk with validation.

    Args:
        har_path: Path to HAR file

    Returns:
        HAR data dict

    Raises:
        ValueError: If HAR format is invalid
        FileNotFoundError: If file doesn't exist
    """
    if not har_path.exists():
        raise FileNotFoundError(f"HAR file not found: {har_path}")

    try:
        with open(har_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if 'log' not in data or 'entries' not in data['log']:
            raise ValueError("Invalid HAR format: missing log.entries")

        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"HAR file is not valid JSON: {e}")


# ============================================================================
# ENTRY SUMMARIZATION (Token Reduction)
# ============================================================================

def extract_entry_summary(entry: dict) -> dict:
    """
    Extract essential info from HAR entry for LLM analysis.
    Reduces token count by removing unnecessary fields.

    Args:
        entry: Full HAR entry dict

    Returns:
        Condensed entry with only essential fields
    """
    request = entry.get('request', {})
    response = entry.get('response', {})
    content = response.get('content', {})

    # Extract method and URL
    method = request.get('method', 'GET')
    url = request.get('url', '')
    parsed_url = urlparse(url)

    # Extract important headers (auth, content-type, etc.)
    important_header_names = ['authorization', 'content-type', 'accept', 'x-', 'csrf', 'api-key']
    important_headers = {}
    for header in request.get('headers', []):
        name = header.get('name', '').lower()
        if any(important in name for important in important_header_names):
            important_headers[header.get('name', '')] = header.get('value', '')

    # Extract query parameters
    query_params = {}
    if parsed_url.query:
        try:
            query_params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed_url.query).items()}
        except:
            pass

    # Extract response info
    status = response.get('status', 0)
    mime_type = content.get('mimeType', '')
    response_size = content.get('size', 0)

    # Truncate response body (keep first 1000 chars for context)
    response_text = content.get('text', '')
    if len(response_text) > 1000:
        response_text = response_text[:1000] + '...[truncated]'

    # Extract timing
    time_ms = entry.get('time', 0)

    return {
        'method': method,
        'url': url,
        'domain': parsed_url.hostname or '',
        'path': parsed_url.path or '/',
        'query_params': query_params,
        'headers': important_headers,
        'status': status,
        'mime_type': mime_type,
        'response_size': response_size,
        'response_sample': response_text,
        'timing_ms': round(time_ms, 2) if time_ms is not None else None,
    }


# ============================================================================
# ENDPOINT GROUPING
# ============================================================================

def normalize_path(path: str) -> str:
    """
    Normalize URL path by replacing IDs/UUIDs with placeholders.

    Examples:
        /api/users/123 → /api/users/{id}
        /api/v1/users/123 → /api/v1/users/{id} (preserves version)
        /api/users/abc-def-123 → /api/users/{id}
        /posts/2024/12/05 → /posts/{year}/{month}/{day}
    """
    # Replace numeric IDs, but preserve version numbers (v1, v2, etc.)
    # Use negative lookbehind to skip digits preceded by 'v' or 'V'
    path = re.sub(r'(?<![vV])/(\d+)([/?]|$)', r'/{id}\2', path)

    # Replace UUIDs and long alphanumeric IDs (both upper and lowercase hex)
    path = re.sub(r'/[a-fA-F0-9]{8,}([/?]|$)', r'/{id}\1', path)
    path = re.sub(r'/[a-zA-Z0-9\-_]{20,}([/?]|$)', r'/{id}\1', path)

    # Replace dates (YYYY/MM/DD or YYYY-MM-DD)
    path = re.sub(r'/\d{4}/\d{1,2}/\d{1,2}', '/{year}/{month}/{day}', path)
    path = re.sub(r'/\d{4}-\d{2}-\d{2}', '/{date}', path)

    return path


def group_similar_endpoints(entries: list[dict]) -> list[dict]:
    """
    Group similar requests (same method + path pattern) together.
    Reduces redundancy for LLM analysis.

    Args:
        entries: List of summarized HAR entries

    Returns:
        List of grouped entries with pattern and examples
    """
    # Group by method + normalized path
    groups = defaultdict(list)

    for entry in entries:
        method = entry.get('method', 'GET')
        path = entry.get('path', '/')
        normalized = normalize_path(path)
        key = f"{method} {normalized}"
        groups[key].append(entry)

    # Create grouped entries
    grouped = []
    for key, group_entries in groups.items():
        method, pattern = key.split(' ', 1)

        # Take first entry as representative
        representative = group_entries[0].copy()
        representative['path_pattern'] = pattern
        representative['call_count'] = len(group_entries)

        # Aggregate timing
        timings = [e.get('timing_ms') for e in group_entries if e.get('timing_ms') is not None]
        if timings:
            representative['timing_avg_ms'] = round(sum(timings) / len(timings), 2)

        # Keep up to 3 example URLs
        representative['example_urls'] = [e['url'] for e in group_entries[:3]]

        grouped.append(representative)

    return grouped


# ============================================================================
# TOKEN ESTIMATION AND CHUNKING
# ============================================================================

def estimate_token_count(text: str) -> int:
    """
    Rough estimate of token count.
    Rule of thumb: 1 token ≈ 4 characters

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    return len(text) // 4


def chunk_har_entries(entries: list[dict], max_tokens: int = 30000) -> list[list[dict]]:
    """
    Split HAR entries into chunks that fit within token limits.
    Each chunk is analyzed separately, then results are merged.

    Strategy:
    1. Group similar endpoints first
    2. Chunk by estimated token count
    3. Ensure each chunk has context

    Args:
        entries: List of HAR entry dicts
        max_tokens: Maximum tokens per chunk

    Returns:
        List of entry chunks
    """
    # First, group similar endpoints to reduce redundancy
    grouped = group_similar_endpoints(entries)

    # Now chunk the grouped entries
    chunks = []
    current_chunk = []
    current_tokens = 0

    for entry in grouped:
        # Estimate tokens for this entry (as JSON)
        entry_json = json.dumps(entry, indent=2)
        entry_tokens = estimate_token_count(entry_json)

        # Check if single entry exceeds max_tokens (can't split, must include with warning)
        if entry_tokens > max_tokens:
            # If current chunk has entries, save it first
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_tokens = 0
            # Add oversized entry as its own chunk (unavoidable)
            chunks.append([entry])
            continue

        # If adding this entry would exceed limit, start new chunk
        if current_tokens + entry_tokens > max_tokens and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_tokens = 0

        current_chunk.append(entry)
        current_tokens += entry_tokens

    # Add final chunk
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


# ============================================================================
# LLM-FRIENDLY SUMMARIZATION
# ============================================================================

def summarize_har_for_llm(entries: list[dict]) -> str:
    """
    Create LLM-friendly summary of HAR entries.
    Format as structured JSON with minimal nesting.

    Args:
        entries: List of HAR entry dicts (already summarized)

    Returns:
        JSON string ready for LLM prompt
    """
    summary = {
        "total_entries": len(entries),
        "requests": []
    }

    for entry in entries:
        request_summary = {
            "method": entry.get('method'),
            "url": entry.get('url'),
            "domain": entry.get('domain'),
            "path": entry.get('path_pattern', entry.get('path')),
            "status": entry.get('status'),
            "response_type": entry.get('mime_type'),
        }

        # Add optional fields if present
        if entry.get('query_params'):
            request_summary['query_params'] = entry.get('query_params')

        if entry.get('headers'):
            request_summary['important_headers'] = entry.get('headers')

        if entry.get('response_sample'):
            request_summary['response_sample'] = entry.get('response_sample')

        if entry.get('call_count', 1) > 1:
            request_summary['call_frequency'] = entry.get('call_count')
            request_summary['examples'] = entry.get('example_urls', [])

        summary["requests"].append(request_summary)

    return json.dumps(summary, indent=2, ensure_ascii=False)


# ============================================================================
# COOKIES AND HTML METADATA
# ============================================================================

def extract_cookies_info(cookies_path: Path) -> dict:
    """
    Extract authentication-relevant cookies.

    Args:
        cookies_path: Path to cookies.json file

    Returns:
        Dict with auth_cookies and all_cookie_names
    """
    if not cookies_path.exists():
        return {
            'auth_cookies': [],
            'all_cookie_names': [],
        }

    try:
        with open(cookies_path, 'r', encoding='utf-8') as f:
            cookies = json.load(f)

        # Extract cookies that look like auth tokens
        auth_keywords = ['token', 'auth', 'session', 'jwt', 'bearer', 'api', 'key', 'credential', 'csrf']
        auth_cookies = []

        for cookie in cookies:
            name = cookie.get('name', '').lower()
            if any(keyword in name for keyword in auth_keywords):
                auth_cookies.append({
                    'name': cookie.get('name'),
                    'domain': cookie.get('domain'),
                    'secure': cookie.get('secure', False),
                    'httpOnly': cookie.get('httpOnly', False),
                })

        return {
            'auth_cookies': auth_cookies,
            'all_cookie_names': [c.get('name', '') for c in cookies],
        }
    except Exception:
        return {
            'auth_cookies': [],
            'all_cookie_names': [],
        }


def extract_html_metadata(html_files: list[Path]) -> dict:
    """
    Quick parse of HTML files to extract useful context.

    Args:
        html_files: List of HTML file paths

    Returns:
        Dict with page_titles and visited_urls
    """
    metadata = {
        'page_count': len(html_files),
        'page_titles': [],
        'visited_urls': [],
    }

    for html_file in html_files:
        try:
            # Extract URL hint from filename
            # Format: page_N_sanitized_url.html
            # Note: URL is sanitized (special chars replaced with _), cannot be fully reconstructed
            filename = html_file.stem  # Remove .html
            parts = filename.split('_', 2)  # Split on first 2 underscores
            if len(parts) >= 3:
                # Keep sanitized URL as reference (reconstruction is unreliable)
                sanitized_url = parts[2]
                metadata['visited_urls'].append(f"[sanitized] {sanitized_url}")

            # Could extract title from HTML, but that requires parsing
            # For now, just use filename
            metadata['page_titles'].append(html_file.name)
        except Exception:
            continue

    return metadata
