# Browser Automation Web Scraper

AI-powered web scraper using `browser-use` and Playwright. Captures complete browser sessions including HTTP requests/responses (HAR files), cookies, and HTML content.

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
uv pip install browser-use playwright aiohttp
uvx browser-use install
playwright install chromium
```

**4. Create .env file**

```bash
# Required
XAI_API_KEY=your_xai_api_key_here

# Add credentials for websites you want to scrape
LINKEDIN_EMAIL=your_email@example.com
LINKEDIN_PASSWORD=your_password
TWITTER_EMAIL=your_twitter_email
TWITTER_PASSWORD=your_twitter_password
```

## Usage

### Quick Start

**Run the scraper for the first time:**
```bash
python main.py
```

This creates two template configs in `examples/templates/`:
- `with_login_template.json` - LinkedIn example (with authentication)
- `without_login_template.json` - Hacker News example (no authentication)

Copy a template to `examples/` and edit for your website.

### Using Pre-Made Configurations

The `examples/` folder contains ready-to-use configurations:

**With Login:**
```bash
# LinkedIn - Profile with experience and certifications
python main.py --config examples/linkedin_config.json

# Twitter/X - Timeline and profile
python main.py --config examples/twitter_config.json

# GitHub - Profile and repositories
python main.py --config examples/github_config.json
```

**Without Login:**
```bash
# Hacker News - Front page and comments (no credentials needed)
python main.py --config examples/hackernews_config.json
```

### Creating Custom Configurations

**Step 1: Generate templates (first time only)**
```bash
python main.py
```

This creates `examples/templates/with_login_template.json` and `without_login_template.json`.

**Step 2: Copy and customize**

```bash
# Copy the appropriate template
cp examples/templates/with_login_template.json examples/my_website.json

# Or for sites without login
cp examples/templates/without_login_template.json examples/my_website.json

# Edit the config
# Then run your custom scraper
python main.py --config examples/my_website.json
```

### Configuration Examples

**With Login (LinkedIn):**
```json
{
  "website_name": "linkedin",
  "needs_login": true,
  "login_url": "https://www.linkedin.com/login",
  "credentials": {
    "email_env_var": "LINKEDIN_EMAIL",
    "password_env_var": "LINKEDIN_PASSWORD"
  },
  "task": "Login and navigate to profile:\n1. Use navigate action to go to https://www.linkedin.com/login\n2. Fill email with {email} from sensitive_data\n3. Fill password with {password} from sensitive_data\n4. Click Sign in\n5. Navigate to profile\n6. Use done action",
  "storage_state_file": "linkedin_auth_state.json"
}
```

**Without Login (Hacker News):**
```json
{
  "website_name": "hackernews",
  "needs_login": false,
  "task": "Browse Hacker News:\n1. Use navigate action to go to https://news.ycombinator.com\n2. Wait 2 seconds\n3. Scroll down to load more posts\n4. Click on first post\n5. Use done action"
}
```

**Minimum Required Fields:**
- `website_name` - Identifier for output folder
- `task` - What the agent should do

## What Gets Captured

```
output/{website_name}_{timestamp}/
├── cookies.json              # All browser cookies
├── requests.har              # Complete HTTP traffic with response bodies
├── page_1_*.html             # HTML snapshot of first page
├── page_2_*.html             # HTML snapshot of second page
└── page_n_*.html             # HTML for each navigation
```

### What's in Each File

**cookies.json**
- All browser cookies from the session
- Includes authentication tokens, session IDs, preferences
- Standard JSON format

**requests.har**
- Complete HTTP request/response log
- Includes response bodies (JSON, HTML, etc.)
- Headers, timing, status codes
- Standard HAR 1.2 format (works with Chrome DevTools, Postman)

**page_*.html**
- HTML snapshot captured on every navigation
- Numbered sequentially
- Includes dynamically loaded content

## Features

### Authentication Persistence

First run: Logs in and saves authentication to `{website}_auth_state.json`

Subsequent runs: Loads saved auth (no credentials needed)

**To force re-login:**
```bash
rm linkedin_auth_state.json
```

### AI-Powered Navigation

Uses Grok LLM to intelligently navigate websites based on your task description.

### Complete Data Capture

- HAR recording captures ALL network traffic
- HTML snapshots on every page navigation
- Cookies extracted after session completes

## Project Structure

```
browser-use-scrapping/
├── main.py                    # Universal web scraper
├── examples/
│   ├── templates/             # Template configurations (auto-generated)
│   │   ├── with_login_template.json
│   │   └── without_login_template.json
│   ├── linkedin_config.json   # Pre-made configs
│   ├── twitter_config.json
│   ├── github_config.json
│   └── hackernews_config.json
└── output/                    # Scraping results
```

## Learn More

Check `examples/README.md` for:
- Detailed configuration guide
- Tips for writing effective tasks
- Troubleshooting common issues