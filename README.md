# Browser Automation Web Scraper

AI-powered web scraper using `browser-use` and Playwright. Captures complete browser sessions including HTTP requests/responses (HAR files), cookies, and HTML content. Includes tools for API reverse engineering, endpoint testing, and Markdown report generation.

## Features

- **AI-Powered Navigation** - Uses Grok LLM to intelligently navigate websites
- **Complete Data Capture** - HAR files, cookies, HTML snapshots
- **Stealth Mode** - Evades basic bot detection with fingerprint masking
- **API Discovery** - Reverse engineer APIs from captured traffic
- **Endpoint Testing** - Automatically test discovered endpoints with captured cookies
- **Markdown Reports** - Generate human-readable API documentation
- **Authentication Persistence** - Save/load login sessions

## Installation

**1. Create environment with [uv](https://docs.astral.sh/uv/) (Python>=3.11):**

```bash
pip install uv
uv venv --python 3.12
```

**2. Activate environment**

```bash
source .venv/bin/activate
# On Windows: .venv\Scripts\activate
```

**3. Install dependencies:**

```bash
uv pip install browser-use playwright langchain-openai aiohttp python-dotenv
playwright install chromium
```

**4. Create .env file**

```bash
# Required
XAI_API_KEY=your_xai_api_key_here

# Add credentials for websites you want to scrape
LINKEDIN_EMAIL=your_email@example.com
LINKEDIN_PASSWORD=your_password
ABLY_EMAIL=your_ably_email
ABLY_PASSWORD=your_ably_password
```

## Quick Start

### Full Pipeline: Scrape → Analyze → Test → Report

```bash
# Step 1: Scrape a website
python main.py --config examples/ably_config.json

# Step 2: Analyze HAR to discover API endpoints
python analyze_har.py \
    --output-dir output/ably_20251208_114008 \
    --config examples/ably_config.json \
    --methods GET \
    --data-only

# Step 3: Test discovered endpoints
python test_endpoints.py --output-dir output/ably_20251208_114008

# Step 4: Generate Markdown report
python generate_report.py --output-dir output/ably_20251208_114008
```

### First Time Setup

```bash
# Run without config to generate templates
python main.py
```

This creates two template configs in `examples/templates/`:
- `with_login_template.json` - For sites requiring authentication
- `without_login_template.json` - For public sites

## Usage

### 1. Web Scraping (`main.py`)

**With Login:**
```bash
python main.py --config examples/ably_config.json
python main.py --config examples/linkedin_config.json
```

**Without Login:**
```bash
python main.py --config examples/hackernews_config.json
```

**What gets captured:**
```
output/{website_name}_{timestamp}/
├── cookies.json       # All browser cookies
├── requests.har       # Complete HTTP traffic with response bodies
├── page_1_*.html      # HTML snapshot of first page
├── page_2_*.html      # HTML snapshot of second page
└── page_n_*.html      # HTML for each navigation
```

### 2. API Discovery (`analyze_har.py`)

Reverse engineer APIs from captured HAR files using AI.

```bash
python analyze_har.py \
    --output-dir output/ably_20251208_114008 \
    --config examples/ably_config.json
```

**Options:**
| Flag | Description |
|------|-------------|
| `--output-dir` | Path to scraper output directory (required) |
| `--config` | Path to scraper config file (required) |
| `--methods` | Filter by HTTP methods, e.g., `GET` or `GET,POST` |
| `--data-only` | Only include data/API endpoints (skip HTML, static assets) |
| `--max-tokens-per-chunk` | LLM chunk size (default: 30000) |

**Example with filtering:**
```bash
# Only GET requests that return data (JSON, XML, etc.)
python analyze_har.py \
    --output-dir output/ably_20251208_114008 \
    --config examples/ably_config.json \
    --methods GET \
    --data-only
```

**Output:** `api_endpoints.json` with discovered API documentation:
```json
{
  "endpoints": [
    {
      "method": "GET",
      "path": "/api/users/{id}/profile",
      "domain": "api.example.com",
      "endpoint_name": "Get User Profile",
      "purpose": "Fetches user profile data",
      "auth_method": "cookie",
      "parameters": [...],
      "response_format": "application/json"
    }
  ]
}
```

### 3. Endpoint Testing (`test_endpoints.py`)

Automatically test discovered endpoints using captured cookies.

```bash
python test_endpoints.py --output-dir output/ably_20251208_114008
```

**Options:**
| Flag | Description |
|------|-------------|
| `--output-dir` | Path to output directory (required) |
| `--timeout` | Request timeout in seconds (default: 10) |
| `--delay` | Delay between requests in seconds (default: 1.0) |
| `--output-file` | Output filename (default: endpoint_test_results.json) |

**Output:** `endpoint_test_results.json` with test results:
```json
{
  "website_name": "ably",
  "total_endpoints": 5,
  "successful_requests": 4,
  "failed_requests": 1,
  "results": [
    {
      "endpoint_name": "Get App Stats",
      "method": "GET",
      "url": "https://ably.com/api/apps/123/stats",
      "status_code": 200,
      "status": "success",
      "response_time_ms": 245.32,
      "response_json": {...}
    }
  ]
}
```

### 4. Markdown Report (`generate_report.py`)

Generate a human-readable Markdown report showing endpoints and their responses.

```bash
python generate_report.py --output-dir output/ably_20251208_114008
```

**Options:**
| Flag | Description |
|------|-------------|
| `--output-dir` | Path to output directory (required) |
| `--output-file` | Output filename (default: api_report.md) |

**Output:** `api_report.md` with:
- Task that was performed
- Summary statistics (total endpoints, success/failure counts)
- Endpoints overview table grouped by domain
- Detailed endpoint documentation with actual responses
- Usage examples (curl commands)

**Example report structure:**
```markdown
# API Endpoints Report: ably

## Task Performed
...

## Summary
| Metric | Value |
|--------|-------|
| Total Endpoints | 5 |
| Successful Requests | 4 |

## Endpoints Overview
### ably.com
| Method | Endpoint | Status | Response Time |
|--------|----------|--------|---------------|
| `GET` | `/api/apps/{id}/stats` | 200 | 245ms |

## Endpoint Details
### 1. Get App Stats
**URL:** `https://ably.com/api/apps/123/stats`
**Response:**
```json
{"data": "..."}
```
```

## Configuration

### With Login
```json
{
  "website_name": "ably",
  "needs_login": true,
  "credentials": {
    "email_env_var": "ABLY_EMAIL",
    "password_env_var": "ABLY_PASSWORD"
  },
  "storage_state_file": "ably_auth_state.json",
  "task": "Login and explore:\n1. Navigate to https://ably.com/login\n2. Enter email and password\n3. Click login\n4. Explore dashboard\n5. Use done action"
}
```

### Without Login
```json
{
  "website_name": "hackernews",
  "needs_login": false,
  "task": "Browse Hacker News:\n1. Navigate to https://news.ycombinator.com\n2. Scroll down\n3. Click first post\n4. Use done action"
}
```

### Minimum Required Fields
- `website_name` - Identifier for output folder
- `task` - What the agent should do

## Stealth Mode

The scraper includes stealth features to evade basic bot detection:

- User agent spoofing
- Timezone and geolocation masking
- WebDriver property hiding
- Plugin and language mocking
- Chrome runtime emulation
- Permissions API mocking

**Note:** Stealth mode helps with basic detection but may not bypass enterprise-grade protection (Akamai, PerimeterX, Cloudflare Bot Management).

## Project Structure

```
browser-use-scrapping/
├── main.py                    # Universal web scraper
├── analyze_har.py             # HAR API endpoint analyzer
├── test_endpoints.py          # Endpoint tester
├── generate_report.py         # Markdown report generator
├── har_utils/                 # HAR analysis utilities
│   ├── __init__.py
│   ├── filters.py             # Tracking/analytics filtering
│   ├── models.py              # Pydantic models for API endpoints
│   ├── parser.py              # HAR parsing and chunking
│   └── analyzer.py            # LLM-powered API discovery
├── examples/
│   ├── templates/             # Template configurations (auto-generated)
│   │   ├── with_login_template.json
│   │   └── without_login_template.json
│   ├── ably_config.json       # Ably (with login)
│   ├── linkedin_config.json   # LinkedIn (with login)
│   ├── twitter_config.json    # Twitter/X (with login)
│   ├── github_config.json     # GitHub (with login)
│   └── hackernews_config.json # Hacker News (no login)
└── output/                    # Scraping results
    └── {website}_{timestamp}/
        ├── cookies.json
        ├── requests.har
        ├── page_*.html
        ├── api_endpoints.json          # From analyze_har.py
        ├── endpoint_test_results.json  # From test_endpoints.py
        └── api_report.md               # From generate_report.py
```

## Authentication Persistence

First run: Logs in and saves authentication to `{website}_auth_state.json`

Subsequent runs: Loads saved auth (no credentials needed)

**To force re-login:**
```bash
rm ably_auth_state.json
```

## HAR Filtering

The analyzer aggressively filters noise from HAR files:

**Filtered out:**
- Google Analytics, Facebook Pixel, Segment, Mixpanel
- Sentry, LogRocket, Hotjar, FullStory
- Intercom, Zendesk, Drift (chat widgets)
- CDN static assets (JS, CSS, fonts, images)
- Tracking pixels and beacons
- Failed requests

**Kept:**
- API endpoints (JSON/XML responses)
- Data-fetching requests
- Authentication endpoints
- Search/query endpoints

## Troubleshooting

### Bot Detection
If you get blocked:
1. Some sites have enterprise-grade protection that can't be bypassed
2. Try adding delays between actions in your task
3. Use realistic browsing patterns

### Missing Endpoints
If the analyzer misses endpoints:
1. Remove `--data-only` flag to include all requests
2. Remove `--methods` filter to include POST/PUT/DELETE
3. Increase `--max-tokens-per-chunk` for larger HAR files

### Cookie Issues
If endpoint tests fail with 401/403:
1. Cookies may have expired - re-run the scraper
2. Some endpoints may require additional headers
3. Check if the site uses short-lived tokens

## Requirements

- Python 3.11+
- XAI API key (for Grok LLM)
- Chromium browser (installed via Playwright)
