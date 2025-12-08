#!/usr/bin/env python3
"""
API Endpoint Tester

Automatically tests discovered API endpoints using captured cookies and sessions.

Usage:
    python test_endpoints.py --output-dir output/pettapp-seven_20251205_094318
    python test_endpoints.py --output-dir output/linkedin_20251204_105022
"""

import argparse
import json
import logging
from pathlib import Path
import requests
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs, urlencode
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# COOKIE CONVERSION
# ============================================================================

def load_cookies_for_requests(cookies_path: Path) -> Dict[str, requests.cookies.RequestsCookieJar]:
    """
    Load cookies from JSON and organize by domain for requests library.

    Args:
        cookies_path: Path to cookies.json

    Returns:
        Dict mapping domain to RequestsCookieJar
    """
    if not cookies_path.exists():
        logger.warning(f"Cookies file not found: {cookies_path}")
        return {}

    with open(cookies_path, 'r', encoding='utf-8') as f:
        cookies = json.load(f)

    # Organize cookies by domain
    cookies_by_domain = {}

    for cookie in cookies:
        domain = cookie.get('domain', '')
        if not domain:
            continue

        # Clean domain (remove leading dot)
        clean_domain = domain.lstrip('.')

        if clean_domain not in cookies_by_domain:
            cookies_by_domain[clean_domain] = requests.cookies.RequestsCookieJar()

        # Add cookie to jar
        cookies_by_domain[clean_domain].set(
            name=cookie.get('name', ''),
            value=cookie.get('value', ''),
            domain=domain,
            path=cookie.get('path', '/'),
            secure=cookie.get('secure', False),
        )

    logger.info(f"Loaded cookies for {len(cookies_by_domain)} domains")
    return cookies_by_domain


def get_cookies_for_url(url: str, cookies_by_domain: Dict) -> requests.cookies.RequestsCookieJar:
    """
    Get appropriate cookies for a URL.

    Args:
        url: Target URL
        cookies_by_domain: Cookie jars organized by domain

    Returns:
        RequestsCookieJar with relevant cookies
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ''

    # Try exact domain match first
    if hostname in cookies_by_domain:
        return cookies_by_domain[hostname]

    # Try subdomain match (e.g., api.example.com matches example.com)
    # Must be exact match or proper subdomain (with dot separator)
    for domain, jar in cookies_by_domain.items():
        if hostname == domain or hostname.endswith('.' + domain):
            return jar

    # Return empty jar
    return requests.cookies.RequestsCookieJar()


# ============================================================================
# ENDPOINT TESTING
# ============================================================================

def test_endpoint(endpoint: dict, cookies_by_domain: Dict, timeout: int = 10) -> dict:
    """
    Test a single API endpoint and capture response.

    Args:
        endpoint: Endpoint dict from api_endpoints.json
        cookies_by_domain: Cookies organized by domain
        timeout: Request timeout in seconds

    Returns:
        Dict with test results
    """
    method = endpoint.get('method', 'GET')
    url = endpoint.get('full_url', '')
    endpoint_name = endpoint.get('endpoint_name', 'Unknown')

    logger.info(f"Testing: {method} {url}")

    # Get cookies for this URL
    cookies = get_cookies_for_url(url, cookies_by_domain)

    # Prepare headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/html, */*',
    }

    # Add required headers from endpoint
    required_headers = endpoint.get('required_headers', {})
    headers.update(required_headers)

    # Prepare parameters
    query_params = {}
    body_params = None  # Initialize as None, only create dict if body params exist

    for param in endpoint.get('parameters', []):
        location = param.get('location', 'query')
        name = param.get('name', '')
        value = param.get('example_value', '')

        if location == 'query':
            query_params[name] = value
        elif location == 'body':
            if body_params is None:
                body_params = {}
            body_params[name] = value
        elif location == 'header':
            headers[name] = value

    try:
        # Make request
        start_time = time.time()

        if method.upper() == 'GET':
            response = requests.get(
                url,
                params=query_params,
                headers=headers,
                cookies=cookies,
                timeout=timeout,
                allow_redirects=True
            )
        elif method.upper() == 'POST':
            post_kwargs = {
                'params': query_params,
                'headers': headers,
                'cookies': cookies,
                'timeout': timeout,
                'allow_redirects': True
            }
            if body_params is not None:
                post_kwargs['json'] = body_params
            response = requests.post(url, **post_kwargs)
        elif method.upper() == 'PUT':
            put_kwargs = {
                'params': query_params,
                'headers': headers,
                'cookies': cookies,
                'timeout': timeout,
                'allow_redirects': True
            }
            if body_params is not None:
                put_kwargs['json'] = body_params
            response = requests.put(url, **put_kwargs)
        elif method.upper() == 'DELETE':
            response = requests.delete(
                url,
                params=query_params,
                headers=headers,
                cookies=cookies,
                timeout=timeout,
                allow_redirects=True
            )
        elif method.upper() == 'PATCH':
            patch_kwargs = {
                'params': query_params,
                'headers': headers,
                'cookies': cookies,
                'timeout': timeout,
                'allow_redirects': True
            }
            if body_params is not None:
                patch_kwargs['json'] = body_params
            response = requests.patch(url, **patch_kwargs)
        else:
            # Default to GET for unknown methods
            logger.warning(f"Unknown HTTP method '{method}', defaulting to GET")
            response = requests.get(
                url,
                params=query_params,
                headers=headers,
                cookies=cookies,
                timeout=timeout,
                allow_redirects=True
            )

        elapsed_ms = (time.time() - start_time) * 1000

        # Parse response
        content_type = response.headers.get('Content-Type', '')
        response_text = response.text

        # Try to parse JSON
        response_json = None
        if 'application/json' in content_type:
            try:
                response_json = response.json()
            except:
                pass

        # Truncate large responses
        if len(response_text) > 10000:
            response_text_truncated = response_text[:10000] + f"\n... [truncated, total {len(response_text)} chars]"
        else:
            response_text_truncated = response_text

        result = {
            'endpoint_name': endpoint_name,
            'method': method,
            'url': url,
            'status_code': response.status_code,
            'status': 'success' if response.status_code < 400 else 'error',
            'response_time_ms': round(elapsed_ms, 2),
            'content_type': content_type,
            'response_size_bytes': len(response.content),
            'response_headers': dict(response.headers),
            'response_text': response_text_truncated,
            'response_json': response_json,
            'cookies_used': len(cookies),
        }

        logger.info(f"✓ {response.status_code} - {elapsed_ms:.0f}ms - {endpoint_name}")
        return result

    except requests.exceptions.Timeout:
        logger.error(f"✗ Timeout - {endpoint_name}")
        return {
            'endpoint_name': endpoint_name,
            'method': method,
            'url': url,
            'status': 'timeout',
            'error': f'Request timeout after {timeout}s'
        }
    except requests.exceptions.ConnectionError as e:
        logger.error(f"✗ Connection Error - {endpoint_name}")
        return {
            'endpoint_name': endpoint_name,
            'method': method,
            'url': url,
            'status': 'connection_error',
            'error': str(e)
        }
    except Exception as e:
        logger.error(f"✗ Error - {endpoint_name}: {e}")
        return {
            'endpoint_name': endpoint_name,
            'method': method,
            'url': url,
            'status': 'error',
            'error': str(e)
        }


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Test discovered API endpoints with captured cookies',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_endpoints.py --output-dir output/pettapp-seven_20251205_094318
  python test_endpoints.py --output-dir output/linkedin_20251204_105022 --timeout 15
        """
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        required=True,
        help='Path to output directory containing api_endpoints.json and cookies.json'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=10,
        help='Request timeout in seconds (default: 10)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay between requests in seconds (default: 1.0)'
    )
    parser.add_argument(
        '--output-file',
        type=str,
        default='endpoint_test_results.json',
        help='Output filename (default: endpoint_test_results.json)'
    )

    args = parser.parse_args()

    # Validate paths
    output_dir = Path(args.output_dir).resolve()
    if not output_dir.exists():
        logger.error(f"Output directory not found: {output_dir}")
        return 1

    endpoints_path = output_dir / "api_endpoints.json"
    cookies_path = output_dir / "cookies.json"
    results_path = output_dir / args.output_file

    if not endpoints_path.exists():
        logger.error(f"API endpoints file not found: {endpoints_path}")
        logger.info("Run analyze_har.py first to discover endpoints")
        return 1

    # Banner
    logger.info("=" * 70)
    logger.info("API ENDPOINT TESTER")
    logger.info("=" * 70)
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Results will be saved to: {results_path}")
    logger.info("")

    try:
        # Load API endpoints
        logger.info("Step 1: Loading API endpoints...")
        with open(endpoints_path, 'r', encoding='utf-8') as f:
            api_data = json.load(f)

        endpoints = api_data.get('endpoints', [])
        logger.info(f"Found {len(endpoints)} endpoints to test")

        if len(endpoints) == 0:
            logger.warning("No endpoints to test")
            return 0

        # Load cookies
        logger.info("\nStep 2: Loading cookies...")
        cookies_by_domain = load_cookies_for_requests(cookies_path)

        # Test endpoints
        logger.info(f"\nStep 3: Testing {len(endpoints)} endpoints...")
        logger.info(f"Timeout: {args.timeout}s, Delay: {args.delay}s between requests\n")

        results = []
        success_count = 0
        error_count = 0

        for i, endpoint in enumerate(endpoints, 1):
            logger.info(f"[{i}/{len(endpoints)}] Testing {endpoint.get('endpoint_name', 'Unknown')}...")

            result = test_endpoint(endpoint, cookies_by_domain, timeout=args.timeout)
            results.append(result)

            if result.get('status') == 'success':
                success_count += 1
            else:
                error_count += 1

            # Delay between requests (be nice to servers)
            if i < len(endpoints):
                time.sleep(args.delay)

        # Create summary
        logger.info("\nStep 4: Generating summary...")

        summary = {
            'website_name': api_data.get('website_name', 'unknown'),
            'test_timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'total_endpoints': len(endpoints),
            'successful_requests': success_count,
            'failed_requests': error_count,
            'timeout_seconds': args.timeout,
            'delay_seconds': args.delay,
            'results': results
        }

        # Save results
        logger.info("\nStep 5: Saving results...")
        with open(results_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        # Summary
        print("\n" + "=" * 70)
        print("✅ ENDPOINT TESTING COMPLETE")
        print("=" * 70)
        print(f"Total Endpoints: {len(endpoints)}")
        print(f"Successful: {success_count} ({success_count/len(endpoints)*100:.1f}%)")
        print(f"Failed: {error_count} ({error_count/len(endpoints)*100:.1f}%)")
        print(f"\n💾 Results saved to: {results_path}")
        print("=" * 70)

        # Show sample results
        if success_count > 0:
            print("\n📊 Sample Successful Responses:")
            for result in results[:3]:
                if result.get('status') == 'success':
                    print(f"\n  • {result['endpoint_name']}")
                    print(f"    {result['method']} {result['url']}")
                    print(f"    Status: {result['status_code']} ({result['response_time_ms']}ms)")
                    if result.get('response_json'):
                        print(f"    Response: {str(result['response_json'])[:100]}...")

        return 0

    except KeyboardInterrupt:
        logger.warning("\nTesting interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Testing failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())
