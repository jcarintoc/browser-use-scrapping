#!/usr/bin/env python3
"""
HAR API Endpoint Analyzer

Reverse-engineers API endpoints from browser scraping sessions using AI.

Usage:
    python analyze_har.py --output-dir output/linkedin_20251204_105022 --config examples/linkedin_config.json
    python analyze_har.py --output-dir output/hackernews_20251204_134249 --config examples/hackernews_config.json
"""

import argparse
import logging
from pathlib import Path
import json
from datetime import datetime
import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from har_utils.filters import filter_har_entries
from har_utils.parser import (
    load_har_file,
    extract_entry_summary,
    chunk_har_entries,
    extract_cookies_info,
    extract_html_metadata,
)
from har_utils.analyzer import HARAnalyzer
from har_utils.models import HARAnalysisResult


# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def load_config_file(config_path: Path) -> dict:
    """
    Load scraper configuration to get original task.

    Args:
        config_path: Path to config JSON file

    Returns:
        Config dict

    Raises:
        FileNotFoundError: If config doesn't exist
        ValueError: If config is invalid JSON
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def validate_output_dir(output_dir: Path) -> bool:
    """
    Validate output directory has required files.

    Args:
        output_dir: Path to output directory

    Returns:
        True if valid, False otherwise
    """
    required_files = ['requests.har', 'cookies.json']
    for filename in required_files:
        file_path = output_dir / filename
        if not file_path.exists():
            logger.error(f"Missing required file: {filename}")
            return False
    return True


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def main():
    """Main entry point"""
    # ========================================================================
    # ARGUMENT PARSING
    # ========================================================================
    parser = argparse.ArgumentParser(
        description='Analyze HAR files to discover API endpoints using AI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analyze_har.py --output-dir output/linkedin_20251204_105022 --config examples/linkedin_config.json
  python analyze_har.py --output-dir output/hackernews_20251204_134249 --config examples/hackernews_config.json
        """
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        required=True,
        help='Path to output directory containing HAR and cookie files'
    )
    parser.add_argument(
        '--config',
        type=str,
        required=True,
        help='Path to scraper config file (to read original task)'
    )
    parser.add_argument(
        '--output-file',
        type=str,
        default='api_endpoints.json',
        help='Output filename (default: api_endpoints.json)'
    )
    parser.add_argument(
        '--max-tokens-per-chunk',
        type=int,
        default=30000,
        help='Maximum tokens per LLM analysis chunk (default: 30000)'
    )
    parser.add_argument(
        '--methods',
        type=str,
        default=None,
        help='Comma-separated list of HTTP methods to include (e.g., "GET" or "GET,POST"). Default: all methods'
    )
    parser.add_argument(
        '--data-only',
        action='store_true',
        help='Only include data/API endpoints (skip HTML pages, static assets)'
    )

    args = parser.parse_args()

    # ========================================================================
    # PATH VALIDATION
    # ========================================================================
    output_dir = Path(args.output_dir).resolve()
    config_path = Path(args.config).resolve()

    if not output_dir.exists():
        logger.error(f"Output directory not found: {output_dir}")
        return 1

    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        return 1

    if not validate_output_dir(output_dir):
        logger.error("Output directory is missing required files")
        return 1

    # Define file paths
    har_path = output_dir / "requests.har"
    cookies_path = output_dir / "cookies.json"
    html_files = list(output_dir.glob("page_*.html"))
    result_path = output_dir / args.output_file

    # ========================================================================
    # BANNER
    # ========================================================================
    logger.info("=" * 70)
    logger.info("HAR API ENDPOINT ANALYZER")
    logger.info("=" * 70)
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Config file: {config_path}")
    logger.info(f"Result will be saved to: {result_path}")
    logger.info("")

    try:
        # ====================================================================
        # STEP 1: Load Configuration
        # ====================================================================
        logger.info("Step 1: Loading configuration...")
        config = load_config_file(config_path)
        website_name = config.get('website_name', 'unknown')
        original_task = config.get('task', 'No task description available')
        logger.info(f"Website: {website_name}")
        logger.info(f"Original task: {original_task[:100]}...")

        # ====================================================================
        # STEP 2: Load and Filter HAR
        # ====================================================================
        logger.info("\nStep 2: Loading and filtering HAR file...")
        har_data = load_har_file(har_path)
        original_entries = har_data.get('log', {}).get('entries', [])
        logger.info(f"Original HAR entries: {len(original_entries)}")

        # Parse method filter
        methods = None
        if args.methods:
            methods = [m.strip().upper() for m in args.methods.split(',')]
            logger.info(f"Filtering to methods: {methods}")

        if args.data_only:
            logger.info("Filtering to data/API endpoints only")

        filtered_entries, filter_stats = filter_har_entries(
            original_entries,
            methods=methods,
            data_endpoints_only=args.data_only
        )
        logger.info(f"After filtering: {len(filtered_entries)} entries")
        logger.info(f"Removed by category:")
        for category, count in filter_stats['removed_by_category'].items():
            if count > 0:
                logger.info(f"  - {category}: {count}")

        if len(filtered_entries) == 0:
            logger.warning("No entries left after filtering! Analysis cannot proceed.")
            logger.info("Creating empty result file...")

            empty_result = HARAnalysisResult(
                website_name=website_name,
                analysis_timestamp=datetime.now().isoformat(),
                original_task=original_task,
                total_requests=len(original_entries),
                filtered_requests=0,
                filter_stats=filter_stats['removed_by_category'],
                endpoints=[],
                total_endpoints=0,
                auth_methods_detected=[],
                cookie_names=[],
                auth_headers=[],
                domains_accessed=[],
                notes="All requests were filtered out (tracking/analytics only)"
            )

            with open(result_path, 'w', encoding='utf-8') as f:
                json.dump(empty_result.model_dump(), f, indent=2, ensure_ascii=False)

            logger.info(f"Empty result saved to: {result_path}")
            return 0

        # ====================================================================
        # STEP 3: Load Supporting Data
        # ====================================================================
        logger.info("\nStep 3: Loading cookies and HTML metadata...")
        cookies_info = extract_cookies_info(cookies_path)
        logger.info(f"Found {len(cookies_info['all_cookie_names'])} cookies")
        if cookies_info['auth_cookies']:
            logger.info(f"Auth cookies: {[c['name'] for c in cookies_info['auth_cookies'][:5]]}")

        html_metadata = extract_html_metadata(html_files)
        logger.info(f"Analyzed {len(html_files)} HTML files")

        # ====================================================================
        # STEP 4: Summarize and Chunk HAR Entries
        # ====================================================================
        logger.info("\nStep 4: Summarizing and chunking HAR entries...")

        # Summarize entries (reduce tokens)
        summarized_entries = []
        for entry in filtered_entries:
            try:
                summary = extract_entry_summary(entry)
                summarized_entries.append(summary)
            except Exception as e:
                logger.warning(f"Failed to summarize entry: {e}")
                continue

        logger.info(f"Summarized {len(summarized_entries)} entries")

        # Chunk for LLM analysis
        chunks = chunk_har_entries(summarized_entries, max_tokens=args.max_tokens_per_chunk)
        logger.info(f"Split into {len(chunks)} chunks for LLM analysis")

        # ====================================================================
        # STEP 5: Analyze with LLM
        # ====================================================================
        logger.info("\nStep 5: Analyzing with LLM...")
        analyzer = HARAnalyzer()

        all_chunk_results = []
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"Analyzing chunk {i}/{len(chunks)} ({len(chunk)} entries)...")
            try:
                chunk_endpoints = analyzer.analyze_har_chunk(
                    har_entries=chunk,
                    cookies_info=cookies_info,
                    task_context=original_task,
                    website_name=website_name
                )
                all_chunk_results.append(chunk_endpoints)
                logger.info(f"Found {len(chunk_endpoints)} endpoints in this chunk")
            except Exception as e:
                logger.error(f"Failed to analyze chunk {i}: {e}")
                logger.warning("Continuing with remaining chunks...")
                all_chunk_results.append([])

        # ====================================================================
        # STEP 6: Merge and Deduplicate
        # ====================================================================
        logger.info("\nStep 6: Merging results...")
        merged_endpoints = analyzer.merge_endpoint_results(all_chunk_results)
        logger.info(f"Total unique endpoints: {len(merged_endpoints)}")

        # ====================================================================
        # STEP 7: Detect Authentication
        # ====================================================================
        logger.info("\nStep 7: Analyzing authentication methods...")
        auth_summary = analyzer.detect_auth_methods(merged_endpoints, cookies_info)

        # ====================================================================
        # STEP 8: Create Final Result
        # ====================================================================
        logger.info("\nStep 8: Building final result...")

        # Extract unique domains
        domains_accessed = list(set(ep.domain for ep in merged_endpoints if ep.domain))

        result = HARAnalysisResult(
            website_name=website_name,
            analysis_timestamp=datetime.now().isoformat(),
            original_task=original_task,
            total_requests=len(original_entries),
            filtered_requests=len(filtered_entries),
            filter_stats=filter_stats['removed_by_category'],
            endpoints=merged_endpoints,
            total_endpoints=len(merged_endpoints),
            auth_methods_detected=auth_summary['methods'],
            cookie_names=auth_summary['cookie_names'],
            auth_headers=auth_summary['headers'],
            domains_accessed=domains_accessed,
        )

        # ====================================================================
        # STEP 9: Save Results
        # ====================================================================
        logger.info("\nStep 9: Saving results...")
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result.model_dump(), f, indent=2, ensure_ascii=False)

        # ====================================================================
        # SUMMARY
        # ====================================================================
        print("\n" + "=" * 70)
        print("✅ API ENDPOINT ANALYSIS COMPLETE")
        print("=" * 70)
        print(f"Website: {website_name}")
        print(f"Total Requests: {len(original_entries)} → {len(filtered_entries)} (after filtering)")
        print(f"\n📊 Filter Statistics:")
        for category, count in filter_stats['removed_by_category'].items():
            if count > 0:
                print(f"   - {category}: {count}")
        print(f"\n🎯 Discovered Endpoints: {len(merged_endpoints)}")
        if auth_summary['methods']:
            print(f"Authentication Methods: {', '.join(m.value for m in auth_summary['methods'])}")
        print(f"\n💾 Results saved to: {result_path}")
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        logger.warning("\nAnalysis interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
