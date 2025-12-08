#!/usr/bin/env python3
"""
API Endpoints Markdown Report Generator

Generates a human-readable Markdown report from endpoint test results.

Usage:
    python generate_report.py --output-dir output/ably_20251208_114008
    python generate_report.py --output-dir output/ably_20251208_114008 --output-file custom_report.md
"""

import argparse
import json
import logging
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from typing import Dict, List, Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def generate_markdown_report(
    summary: dict,
    api_data: dict,
    output_path: Path
) -> None:
    """
    Generate a Markdown report of tested API endpoints with responses.

    Args:
        summary: Test results summary from endpoint_test_results.json
        api_data: Original API endpoints data from api_endpoints.json
        output_path: Path to save the .md file
    """
    lines = []
    website_name = summary.get('website_name', 'Unknown')
    original_task = api_data.get('original_task', 'No task description available')
    results = summary.get('results', [])

    # Header
    lines.append(f"# API Endpoints Report: {website_name}")
    lines.append("")
    lines.append(f"**Generated:** {summary.get('test_timestamp', datetime.now().isoformat())}")
    lines.append("")

    # Task Description
    lines.append("## Task Performed")
    lines.append("")
    lines.append("```")
    lines.append(original_task)
    lines.append("```")
    lines.append("")

    # Summary Statistics
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Endpoints | {summary.get('total_endpoints', 0)} |")
    lines.append(f"| Successful Requests | {summary.get('successful_requests', 0)} |")
    lines.append(f"| Failed Requests | {summary.get('failed_requests', 0)} |")
    lines.append("")

    # Group endpoints by domain
    endpoints_by_domain: Dict[str, List[dict]] = {}
    for result in results:
        url = result.get('url', '')
        parsed = urlparse(url)
        domain = parsed.netloc or 'unknown'
        if domain not in endpoints_by_domain:
            endpoints_by_domain[domain] = []
        endpoints_by_domain[domain].append(result)

    # Endpoints Overview Table
    lines.append("## Endpoints Overview")
    lines.append("")

    for domain in sorted(endpoints_by_domain.keys()):
        domain_results = endpoints_by_domain[domain]
        lines.append(f"### {domain}")
        lines.append("")
        lines.append("| Method | Endpoint | Status | Response Time |")
        lines.append("|--------|----------|--------|---------------|")

        for result in domain_results:
            method = result.get('method', 'GET')
            url = result.get('url', '')
            parsed = urlparse(url)
            path = parsed.path or '/'
            if parsed.query:
                path += f"?..."
            status = result.get('status_code', result.get('status', 'N/A'))
            response_time = result.get('response_time_ms', 'N/A')
            if isinstance(response_time, (int, float)):
                response_time = f"{response_time:.0f}ms"
            lines.append(f"| `{method}` | `{path}` | {status} | {response_time} |")

        lines.append("")

    # Detailed Endpoint Documentation
    lines.append("## Endpoint Details")
    lines.append("")

    for i, result in enumerate(results, 1):
        endpoint_name = result.get('endpoint_name', 'Unnamed Endpoint')
        method = result.get('method', 'GET')
        url = result.get('url', '')
        status_code = result.get('status_code', 'N/A')
        status = result.get('status', 'unknown')

        lines.append(f"### {i}. {endpoint_name}")
        lines.append("")

        # Status indicator
        if status == 'success':
            status_icon = "✅"
        elif status in ('error', 'timeout', 'connection_error'):
            status_icon = "❌"
        else:
            status_icon = "⚠️"

        lines.append(f"**Status:** {status_icon} {status_code} ({status})")
        lines.append("")
        lines.append(f"**Method:** `{method}`")
        lines.append("")
        lines.append(f"**URL:** `{url}`")
        lines.append("")

        # Response metadata
        if result.get('response_time_ms'):
            lines.append(f"**Response Time:** {result['response_time_ms']:.0f}ms")
            lines.append("")

        if result.get('content_type'):
            lines.append(f"**Content-Type:** `{result['content_type']}`")
            lines.append("")

        if result.get('response_size_bytes'):
            size_kb = result['response_size_bytes'] / 1024
            lines.append(f"**Response Size:** {size_kb:.2f} KB")
            lines.append("")

        # Error message if failed
        if result.get('error'):
            lines.append(f"**Error:** {result['error']}")
            lines.append("")

        # Response
        if result.get('response_json') is not None:
            lines.append("**Response:**")
            lines.append("")
            lines.append("```json")
            try:
                response_str = json.dumps(result['response_json'], indent=2, ensure_ascii=False)
                if len(response_str) > 1000:
                    response_str = response_str[:1000] + "\n... [truncated]"
                lines.append(response_str)
            except:
                lines.append(str(result['response_json'])[:1000])
            lines.append("```")
            lines.append("")
        elif result.get('response_text'):
            lines.append("**Response:**")
            lines.append("")
            content_type = result.get('content_type', '')
            if 'html' in content_type:
                lines.append("```html")
            elif 'xml' in content_type:
                lines.append("```xml")
            else:
                lines.append("```")
            response_text = result['response_text']
            if len(response_text) > 1000:
                response_text = response_text[:1000] + "\n... [truncated]"
            lines.append(response_text)
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Footer - How to use
    lines.append("## How to Use These Endpoints")
    lines.append("")
    lines.append("To call these endpoints, you'll need:")
    lines.append("")
    lines.append("1. **Authentication cookies** from `cookies.json`")
    lines.append("2. **Appropriate headers** (User-Agent, Accept, etc.)")
    lines.append("3. **Valid session** - cookies may expire")
    lines.append("")
    lines.append("Example using `curl`:")
    lines.append("")
    lines.append("```bash")
    if results:
        example = results[0]
        lines.append(f"curl -X {example.get('method', 'GET')} \\")
        lines.append(f"  '{example.get('url', 'https://example.com/api')}' \\")
        lines.append("  -H 'Cookie: your_session_cookie=value' \\")
        lines.append("  -H 'Accept: application/json'")
    else:
        lines.append("curl -X GET 'https://example.com/api' \\")
        lines.append("  -H 'Cookie: your_session_cookie=value'")
    lines.append("```")
    lines.append("")

    # Write to file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    logger.info(f"Markdown report saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate Markdown report from endpoint test results',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_report.py --output-dir output/ably_20251208_114008
  python generate_report.py --output-dir output/ably_20251208_114008 --output-file my_report.md
        """
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        required=True,
        help='Path to output directory containing test results'
    )
    parser.add_argument(
        '--output-file',
        type=str,
        default='api_report.md',
        help='Output filename (default: api_report.md)'
    )

    args = parser.parse_args()

    # Validate paths
    output_dir = Path(args.output_dir).resolve()
    if not output_dir.exists():
        logger.error(f"Output directory not found: {output_dir}")
        return 1

    test_results_path = output_dir / "endpoint_test_results.json"
    api_endpoints_path = output_dir / "api_endpoints.json"
    report_path = output_dir / args.output_file

    if not test_results_path.exists():
        logger.error(f"Test results not found: {test_results_path}")
        logger.info("Run test_endpoints.py first to test the endpoints")
        return 1

    if not api_endpoints_path.exists():
        logger.error(f"API endpoints not found: {api_endpoints_path}")
        logger.info("Run analyze_har.py first to discover endpoints")
        return 1

    # Banner
    logger.info("=" * 70)
    logger.info("MARKDOWN REPORT GENERATOR")
    logger.info("=" * 70)
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Report will be saved to: {report_path}")
    logger.info("")

    try:
        # Load test results
        logger.info("Loading test results...")
        with open(test_results_path, 'r', encoding='utf-8') as f:
            test_results = json.load(f)

        # Load API endpoints data
        logger.info("Loading API endpoints data...")
        with open(api_endpoints_path, 'r', encoding='utf-8') as f:
            api_data = json.load(f)

        # Generate report
        logger.info("Generating Markdown report...")
        generate_markdown_report(test_results, api_data, report_path)

        # Summary
        print("\n" + "=" * 70)
        print("✅ REPORT GENERATED")
        print("=" * 70)
        print(f"Website: {test_results.get('website_name', 'Unknown')}")
        print(f"Endpoints documented: {len(test_results.get('results', []))}")
        print(f"\n📄 Report saved to: {report_path}")
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        logger.warning("\nReport generation interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())
