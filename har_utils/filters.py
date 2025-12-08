"""
Aggressive filtering logic for HAR files.

Removes tracking, analytics, CDN, and other noise from HAR data.
"""

import re
from typing import Dict, List, Tuple
from urllib.parse import urlparse


# ============================================================================
# FILTER LISTS - Comprehensive tracking/analytics domains
# ============================================================================

# Analytics & Tracking Services
ANALYTICS_DOMAINS = [
    # Google Analytics & Marketing
    'google-analytics.com', 'googletagmanager.com', 'doubleclick.net',
    'analytics.google.com', 'googleadservices.com', 'googlesyndication.com',
    'googletagservices.com', 'stats.g.doubleclick.net', 'www.googletagmanager.com',

    # Facebook/Meta
    'facebook.com/tr', 'connect.facebook.net', 'facebook-hardware.com',
    'fbcdn.net', 'fb.me', 'facebook.net',

    # Other Major Analytics
    'segment.com', 'segment.io', 'cdn.segment.com', 'api.segment.io',
    'mixpanel.com', 'cdn.mxpnl.com', 'api.mixpanel.com',
    'hotjar.com', 'hotjar.io', 'static.hotjar.com', 'script.hotjar.com',
    'amplitude.com', 'api.amplitude.com', 'cdn.amplitude.com',
    'heap.io', 'heapanalytics.com', 'cdn.heapanalytics.com',

    # Session Replay & Heatmaps
    'fullstory.com', 'rs.fullstory.com',
    'logrocket.com', 'logrocket.io', 'cdn.lr-intake.com',
    'mouseflow.com', 'luckyorange.com', 'inspectlet.com',
    'smartlook.com', 'sessioncam.com', 'crazyegg.com',

    # Error Tracking
    'sentry.io', 'sentry.dev', 'browser.sentry-cdn.com', 'o1234567.ingest.sentry.io',
    'rollbar.com', 'api.rollbar.com',
    'bugsnag.com', 'notify.bugsnag.com',
    'trackjs.com', 'usage.trackjs.com',
    'raygun.io', 'airbrake.io',

    # Customer Support Chat
    'intercom.io', 'intercom.com', 'widget.intercom.io', 'api.intercom.io',
    'drift.com', 'driftt.com', 'js.driftt.com',
    'zendesk.com', 'zdassets.com', 'static.zdassets.com',
    'livechatinc.com', 'livechat.com', 'cdn.livechatinc.com',
    'olark.com', 'static.olark.com',
    'crisp.chat', 'client.crisp.chat',
    'tawk.to',

    # A/B Testing & Optimization
    'optimizely.com', 'cdn.optimizely.com', 'logx.optimizely.com',
    'vwo.com', 'dev.visualwebsiteoptimizer.com',
    'ab.smartnews.com', 'split.io', 'sdk.split.io',
    'launchdarkly.com',

    # Marketing & Attribution
    'branch.io', 'app.link', 'bnc.lt',
    'adjust.com', 'app.adjust.com',
    'appsflyer.com', 'kochava.com', 'singular.net',

    # APM & Monitoring
    'newrelic.com', 'nr-data.net', 'bam.nr-data.net', 'js-agent.newrelic.com',
    'datadoghq.com', 'datadog-logs.com', 'browser-intake-datadoghq.com',
    'elastic.co', 'elastic-cloud.com',
    'splunk.com',

    # Advertising Networks
    'ad.doubleclick.net', 'adnxs.com', 'adsrvr.org',
    'advertising.com', 'criteo.com', 'criteo.net',
    'outbrain.com', 'taboola.com',
    'scorecardresearch.com', 'quantserve.com',
    'rubiconproject.com', 'pubmatic.com',

    # Other Tracking
    'launchdarkly.com', 'statsigapi.net',
    'pendo.io', 'cdn.pendo.io',
    'walkme.com', 'cdn.walkme.com',
]

# CDN Providers (for static assets only)
CDN_DOMAINS = [
    'cloudflare.com', 'cloudfront.net', 'akamaihd.net', 'akamai.net',
    'fastly.net', 'cdn77.com', 'stackpathcdn.com',
    'jsdelivr.net', 'unpkg.com', 'cdnjs.cloudflare.com',
    'maxcdn.com', 'bootstrapcdn.com',
]

# Tracking URL Patterns (regex patterns)
TRACKING_PATTERNS = [
    r'/beacon', r'/pixel', r'/track', r'/collect', r'/event',
    r'/log', r'/analytics', r'/telemetry', r'/metrics',
    r'/impression', r'/click', r'/conversion', r'/pageview',
    r'/timing', r'/__utm\.gif', r'/tr\?', r'/events?/',
    r'/v1/track', r'/api/track', r'/t\.gif', r'/p\.gif',
]

# Tracking Content Types
TRACKING_MIME_TYPES = [
    'image/gif',  # 1x1 tracking pixels
    'image/png',  # Small tracking images
    'application/x-unknown',  # Often beacons
]

# Chrome Internal URLs
CHROME_INTERNAL_PREFIXES = ['chrome://', 'chrome-extension://', 'about:']


# ============================================================================
# FILTER FUNCTIONS
# ============================================================================

def matches_domain(hostname: str, domain: str) -> bool:
    """
    Check if hostname matches domain exactly or is a subdomain.

    Args:
        hostname: The hostname to check (e.g., 'www.analytics.com')
        domain: The domain pattern to match (e.g., 'analytics.com')

    Returns:
        True if hostname matches domain or is a subdomain of it

    Examples:
        matches_domain('analytics.com', 'analytics.com') → True
        matches_domain('www.analytics.com', 'analytics.com') → True
        matches_domain('myanalytics.com', 'analytics.com') → False
    """
    hostname = hostname.lower()
    domain = domain.lower()
    return hostname == domain or hostname.endswith('.' + domain)


def is_tracking_domain(url: str) -> bool:
    """
    Check if URL belongs to known tracking/analytics service.

    Args:
        url: Full URL to check

    Returns:
        True if URL is from a tracking domain
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ''

        for domain in ANALYTICS_DOMAINS:
            if matches_domain(hostname, domain):
                return True
        return False
    except Exception:
        return False


def is_cdn_static_asset(url: str, mime_type: str = '') -> bool:
    """
    Check if URL is a static CDN asset (JS, CSS, images, fonts).

    Args:
        url: Full URL to check
        mime_type: MIME type of the response

    Returns:
        True if this is a static CDN resource
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ''
        path = parsed.path.lower()

        # Check if from CDN domain
        is_cdn = any(matches_domain(hostname, domain) for domain in CDN_DOMAINS)

        # Check if static file extension
        static_extensions = ['.js', '.css', '.woff', '.woff2', '.ttf', '.eot', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp']
        is_static_file = any(path.endswith(ext) for ext in static_extensions)

        # Check if static MIME type
        static_mimes = ['text/css', 'application/javascript', 'text/javascript', 'font/', 'image/']
        is_static_mime = any(mime.lower().startswith(static) for static in static_mimes for mime in [mime_type])

        return is_cdn and (is_static_file or is_static_mime)
    except Exception:
        return False


def is_tracking_pattern(url: str) -> bool:
    """
    Check if URL matches tracking pattern (e.g., /beacon, /pixel, /track).

    Args:
        url: Full URL to check

    Returns:
        True if URL matches a tracking pattern
    """
    try:
        path = urlparse(url).path.lower()
        for pattern in TRACKING_PATTERNS:
            if re.search(pattern, path):
                return True
        return False
    except Exception:
        return False


def is_failed_request(entry: dict) -> bool:
    """
    Check if request failed (status -1, 0, or 5xx without content).

    Args:
        entry: HAR entry dict

    Returns:
        True if request failed
    """
    try:
        response = entry.get('response', {})
        status = response.get('status', 0)

        # Status -1 or 0 indicates failed request
        if status <= 0:
            return True

        # 5xx errors without content are usually failures
        if status >= 500:
            content = response.get('content', {})
            text = content.get('text', '')
            if not text or len(text) < 10:
                return True

        # Check for failure text
        failure_text = response.get('_failureText', '')
        if failure_text:
            return True

        return False
    except Exception:
        return False


def is_tracking_pixel(entry: dict) -> bool:
    """
    Check if response is a 1x1 tracking pixel.

    Args:
        entry: HAR entry dict

    Returns:
        True if this is a tracking pixel
    """
    try:
        response = entry.get('response', {})
        content = response.get('content', {})
        mime_type = content.get('mimeType', '').lower()
        size = content.get('size', 0)

        # Check if it's a tiny image (likely tracking pixel)
        if any(mime in mime_type for mime in ['image/gif', 'image/png']):
            if size < 100:  # 1x1 pixels are typically < 100 bytes
                return True

        # Check if MIME type is suspicious
        if mime_type in TRACKING_MIME_TYPES:
            return True

        return False
    except Exception:
        return False


def is_chrome_internal(url: str) -> bool:
    """
    Check if URL is a Chrome internal protocol.

    Args:
        url: Full URL to check

    Returns:
        True if this is a chrome:// or chrome-extension:// URL
    """
    return any(url.startswith(prefix) for prefix in CHROME_INTERNAL_PREFIXES)


def should_filter_entry(entry: dict) -> Tuple[bool, str]:
    """
    Decide if HAR entry should be filtered out.

    Args:
        entry: HAR entry dict

    Returns:
        Tuple of (should_filter: bool, reason: str)
    """
    try:
        request = entry.get('request', {})
        response = entry.get('response', {})
        url = request.get('url', '')
        mime_type = response.get('content', {}).get('mimeType', '')

        # Check all filter conditions
        if is_chrome_internal(url):
            return (True, 'chrome_internal')

        if is_failed_request(entry):
            return (True, 'failed_request')

        if is_tracking_domain(url):
            return (True, 'tracking_domain')

        if is_tracking_pattern(url):
            return (True, 'tracking_pattern')

        if is_tracking_pixel(entry):
            return (True, 'tracking_pixel')

        if is_cdn_static_asset(url, mime_type):
            return (True, 'cdn_static')

        return (False, '')
    except Exception:
        return (False, '')


def is_data_endpoint(entry: dict) -> bool:
    """
    Check if endpoint is likely a data-fetching API (not page navigation).

    Args:
        entry: HAR entry dict

    Returns:
        True if this looks like a data API endpoint
    """
    try:
        request = entry.get('request', {})
        response = entry.get('response', {})
        url = request.get('url', '')
        mime_type = response.get('content', {}).get('mimeType', '').lower()
        path = urlparse(url).path.lower()

        # JSON responses are always data endpoints
        if 'application/json' in mime_type:
            return True

        # API path patterns
        api_patterns = ['/api/', '/v1/', '/v2/', '/v3/', '/graphql', '/rest/', '/data/']
        if any(pattern in path for pattern in api_patterns):
            return True

        # Skip HTML page navigations (unless they're API responses)
        if 'text/html' in mime_type:
            # Allow HTML if it's from an API path
            if any(pattern in path for pattern in api_patterns):
                return True
            return False

        # Skip static resources
        static_extensions = ['.js', '.css', '.woff', '.woff2', '.ttf', '.eot',
                           '.svg', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp',
                           '.map', '.xml', '.txt']
        if any(path.endswith(ext) for ext in static_extensions):
            return False

        # XML/JSON-like responses
        if any(t in mime_type for t in ['xml', 'json', 'javascript']):
            return True

        return True  # Default to including if not filtered out
    except Exception:
        return True


def filter_har_entries(
    entries: List[dict],
    methods: List[str] = None,
    data_endpoints_only: bool = False
) -> Tuple[List[dict], dict]:
    """
    Apply all filters to HAR entries.

    Args:
        entries: List of HAR entry dicts
        methods: List of HTTP methods to include (e.g., ['GET']). None = all methods
        data_endpoints_only: If True, only include likely data/API endpoints

    Returns:
        Tuple of (filtered_entries: list, filter_stats: dict)

        filter_stats = {
            'original_count': int,
            'filtered_count': int,
            'removed_by_category': {
                'tracking_domain': int,
                'tracking_pattern': int,
                'failed_request': int,
                'tracking_pixel': int,
                'cdn_static': int,
                'chrome_internal': int,
                'method_filtered': int,
                'non_data_endpoint': int,
            }
        }
    """
    filtered_entries = []
    stats = {
        'tracking_domain': 0,
        'tracking_pattern': 0,
        'failed_request': 0,
        'tracking_pixel': 0,
        'cdn_static': 0,
        'chrome_internal': 0,
        'method_filtered': 0,
        'non_data_endpoint': 0,
    }

    # Normalize methods to uppercase
    if methods:
        methods = [m.upper() for m in methods]

    for entry in entries:
        request = entry.get('request', {})
        method = request.get('method', '').upper()

        # Filter by HTTP method
        if methods and method not in methods:
            stats['method_filtered'] += 1
            continue

        # Apply standard filters
        should_filter, reason = should_filter_entry(entry)
        if should_filter:
            stats[reason] = stats.get(reason, 0) + 1
            continue

        # Filter non-data endpoints if requested
        if data_endpoints_only and not is_data_endpoint(entry):
            stats['non_data_endpoint'] += 1
            continue

        filtered_entries.append(entry)

    return filtered_entries, {
        'original_count': len(entries),
        'filtered_count': len(filtered_entries),
        'removed_by_category': stats
    }
