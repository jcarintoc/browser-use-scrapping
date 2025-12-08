"""
LLM-powered HAR analysis and API endpoint discovery.
"""

import os
import json
import logging
from typing import List, Dict
from langchain_openai import ChatOpenAI
from .models import APIEndpoint, AuthMethod, HTTPMethod, APIParameter
import time

logger = logging.getLogger(__name__)


# ============================================================================
# ANALYSIS PROMPT TEMPLATE
# ============================================================================

ANALYSIS_PROMPT_TEMPLATE = """You are an expert API reverse engineer analyzing browser network traffic.

**CONTEXT:**
Website: {website_name}
Original Task: {task_description}
Total Requests Analyzed: {request_count}

**YOUR GOAL:**
Extract ALL meaningful API endpoints from the HAR data below. Ignore static assets, tracking, and analytics - they've already been filtered out.

**HAR DATA:**
{har_summary}

**COOKIES INFO:**
{cookies_summary}

**INSTRUCTIONS:**
1. Identify unique API endpoints (method + path pattern)
2. For each endpoint, determine:
   - Purpose (what does it do?)
   - Category (data_fetch, user_action, authentication, search, etc.)
   - Parameters (query params, body params, important headers)
   - Authentication method (based on headers and cookies)
   - Response structure
   - Example values from actual requests

3. Group similar endpoints:
   - /api/users/123 and /api/users/456 → /api/users/{{id}}
   - Include parameter details and examples

4. Focus on CORE API endpoints that:
   - Fetch or submit data
   - Perform user actions
   - Handle authentication
   - Search or query content

5. Provide clear, descriptive names and purposes

**OUTPUT FORMAT:**
Return a JSON array of API endpoints. Each endpoint must follow this structure:
{{
  "method": "GET|POST|PUT|PATCH|DELETE",
  "path": "/api/path/{{param}}",
  "full_url": "https://example.com/api/path/123",
  "domain": "example.com",
  "endpoint_name": "Descriptive Name",
  "purpose": "What this endpoint does",
  "category": "data_fetch|user_action|authentication|search|etc",
  "parameters": [
    {{
      "name": "param_name",
      "location": "query|body|header",
      "example_value": "example",
      "required": true,
      "param_type": "string|int|bool|etc"
    }}
  ],
  "required_headers": {{
    "Header-Name": "example value"
  }},
  "auth_method": "none|cookie|bearer|api_key|basic|oauth",
  "response_format": "application/json|text/html|etc",
  "response_structure": "Brief description of response structure",
  "example_response": "First 500 chars of response",
  "status_code": 200,
  "call_frequency": 1,
  "timing_avg_ms": 123.45
}}

**IMPORTANT:**
- Only include actual API endpoints (not HTML pages, static files, or tracking)
- Be thorough - extract ALL meaningful endpoints
- Infer purpose from URL path, method, and context
- Keep example responses under 500 characters
- Return ONLY the JSON array, no additional text

**YOUR JSON RESPONSE:**"""


# ============================================================================
# HAR ANALYZER CLASS
# ============================================================================

class HARAnalyzer:
    """Orchestrates AI-powered HAR analysis"""

    def __init__(self, llm_model: str = "grok-4-fast-non-reasoning"):
        """
        Initialize analyzer with LLM.

        Args:
            llm_model: Model name to use

        Raises:
            ValueError: If XAI_API_KEY environment variable is not set
        """
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            raise ValueError(
                "XAI_API_KEY environment variable is not set. "
                "Please set it in your .env file or environment."
            )

        self.llm = ChatOpenAI(
            model=llm_model,
            api_key=api_key,
            base_url="https://api.x.ai/v1",
            temperature=0.3,  # Lower for more consistent extraction
        )
        logger.info(f"Initialized LLM analyzer with model: {llm_model}")

    def analyze_har_chunk(self,
                          har_entries: list[dict],
                          cookies_info: dict,
                          task_context: str,
                          website_name: str = "unknown") -> List[APIEndpoint]:
        """
        Analyze a chunk of HAR entries and extract API endpoints.

        Args:
            har_entries: List of HAR entry dicts (already summarized)
            cookies_info: Cookie information dict
            task_context: Original scraping task description
            website_name: Website identifier

        Returns:
            List of APIEndpoint objects

        Raises:
            Exception: If LLM analysis fails after retries
        """
        from .parser import summarize_har_for_llm

        # Create summaries for prompt
        har_summary = summarize_har_for_llm(har_entries)
        cookies_summary = json.dumps({
            'auth_cookies': [c['name'] for c in cookies_info.get('auth_cookies', [])],
            'total_cookies': len(cookies_info.get('all_cookie_names', [])),
        }, indent=2)

        # Create prompt
        prompt = ANALYSIS_PROMPT_TEMPLATE.format(
            website_name=website_name,
            task_description=task_context,
            request_count=len(har_entries),
            har_summary=har_summary,
            cookies_summary=cookies_summary,
        )

        # Analyze with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Analyzing chunk with LLM (attempt {attempt + 1}/{max_retries})...")
                response = self.llm.invoke(prompt)
                result_text = response.content.strip()

                # Parse JSON response
                endpoints = self._parse_llm_response(result_text)
                logger.info(f"Successfully extracted {len(endpoints)} endpoints")
                return endpoints

            except Exception as e:
                logger.warning(f"Analysis attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    logger.error("All retry attempts exhausted")
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff

    def _parse_llm_response(self, response_text: str) -> List[APIEndpoint]:
        """
        Parse LLM JSON response into APIEndpoint objects.

        Args:
            response_text: Raw LLM response

        Returns:
            List of APIEndpoint objects
        """
        # Clean up response (remove markdown code blocks if present)
        response_text = response_text.strip()
        if response_text.startswith('```'):
            # Remove opening markdown code block marker (```json, ```JSON, ``` etc.)
            first_newline = response_text.find('\n')
            if first_newline != -1:
                response_text = response_text[first_newline + 1:]
            else:
                # All on one line: ```json[...]``` or ```[...]```
                response_text = response_text[3:]
                # Also strip language specifier if present (e.g., "json", "JSON")
                for lang in ['json', 'JSON', 'Json']:
                    if response_text.startswith(lang):
                        response_text = response_text[len(lang):]
                        break

            # Remove closing ``` if present
            response_text = response_text.strip()
            if response_text.endswith('```'):
                response_text = response_text[:-3].strip()

        # Parse JSON
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response text: {response_text[:500]}...")
            raise ValueError(f"LLM response is not valid JSON: {e}")

        # Ensure data is a list of endpoints
        if isinstance(data, dict):
            # LLM may return {"endpoints": [...]} or {"data": [...]} instead of [...]
            # Try common wrapper keys
            for key in ['endpoints', 'data', 'results', 'items', 'api_endpoints']:
                if key in data and isinstance(data[key], list):
                    logger.info(f"Extracted endpoint list from '{key}' wrapper")
                    data = data[key]
                    break
            else:
                # No known wrapper found
                logger.warning(f"LLM returned dict with keys {list(data.keys())}, expected list")
                data = []

        if not isinstance(data, list):
            logger.error(f"LLM response is not a list, got {type(data).__name__}")
            data = []

        # Convert to APIEndpoint objects
        endpoints = []
        for item in data:
            try:
                # Convert string method to enum
                method_str = item.get('method', 'GET').upper()
                try:
                    method = HTTPMethod[method_str]
                except KeyError:
                    method = HTTPMethod.GET

                # Convert string auth method to enum
                auth_str = item.get('auth_method', 'none').lower()
                try:
                    auth_method = AuthMethod[auth_str.upper()]
                except KeyError:
                    auth_method = AuthMethod.NONE

                # Parse parameters
                parameters = []
                for param in item.get('parameters', []):
                    parameters.append(APIParameter(**param))

                # Create endpoint
                endpoint = APIEndpoint(
                    method=method,
                    path=item.get('path', '/'),
                    full_url=item.get('full_url', ''),
                    domain=item.get('domain', ''),
                    endpoint_name=item.get('endpoint_name', 'Unknown Endpoint'),
                    purpose=item.get('purpose', 'Unknown purpose'),
                    category=item.get('category', 'unknown'),
                    parameters=parameters,
                    required_headers=item.get('required_headers', {}),
                    auth_method=auth_method,
                    response_format=item.get('response_format', 'unknown'),
                    response_structure=item.get('response_structure'),
                    example_response=item.get('example_response'),
                    status_code=item.get('status_code', 200),
                    call_frequency=item.get('call_frequency', 1),
                    timing_avg_ms=item.get('timing_avg_ms'),
                )
                endpoints.append(endpoint)
            except Exception as e:
                logger.warning(f"Failed to parse endpoint: {e}")
                continue

        return endpoints

    def merge_endpoint_results(self, chunks_results: List[List[APIEndpoint]]) -> List[APIEndpoint]:
        """
        Merge results from multiple chunks and deduplicate.

        Args:
            chunks_results: List of endpoint lists from different chunks

        Returns:
            Deduplicated list of endpoints
        """
        # Flatten all results
        all_endpoints = []
        for chunk_endpoints in chunks_results:
            all_endpoints.extend(chunk_endpoints)

        # Deduplicate by method + path
        seen = {}
        merged = []

        for endpoint in all_endpoints:
            key = f"{endpoint.method.value} {endpoint.path}"

            if key in seen:
                # Merge with existing
                existing = seen[key]
                # Save original frequencies for weighted average calculation
                orig_existing_freq = existing.call_frequency
                orig_endpoint_freq = endpoint.call_frequency
                # Average timings if both present (must calculate BEFORE updating frequency)
                if existing.timing_avg_ms is not None and endpoint.timing_avg_ms is not None:
                    total_calls = orig_existing_freq + orig_endpoint_freq
                    existing.timing_avg_ms = (
                        (existing.timing_avg_ms * orig_existing_freq +
                         endpoint.timing_avg_ms * orig_endpoint_freq) / total_calls
                    )
                # Sum call frequencies AFTER timing calculation
                existing.call_frequency += endpoint.call_frequency
            else:
                seen[key] = endpoint
                merged.append(endpoint)

        logger.info(f"Merged {len(all_endpoints)} endpoints into {len(merged)} unique endpoints")
        return merged

    def detect_auth_methods(self, endpoints: List[APIEndpoint], cookies_info: dict) -> Dict:
        """
        Analyze authentication patterns across endpoints.

        Args:
            endpoints: List of discovered endpoints
            cookies_info: Cookie information dict

        Returns:
            Dict with authentication summary
        """
        auth_methods_set = set()
        auth_headers_set = set()

        for endpoint in endpoints:
            auth_methods_set.add(endpoint.auth_method)

            # Collect auth-related headers
            for header_name in endpoint.required_headers.keys():
                header_lower = header_name.lower()
                if any(keyword in header_lower for keyword in ['auth', 'token', 'key', 'csrf', 'bearer']):
                    auth_headers_set.add(header_name)

        # Get important cookie names
        cookie_names = [c['name'] for c in cookies_info.get('auth_cookies', [])]

        return {
            'methods': list(auth_methods_set),
            'headers': list(auth_headers_set),
            'cookie_names': cookie_names,
        }
