"""
Simplified LinkedIn Scraper - Captures Only Essential Data

Captures:
1. cookies.json - All browser cookies
2. requests.har - Complete network traffic (requests + responses)
3. page_*.html - HTML snapshot for EVERY page visited

No structured data extraction, just raw browser data.

Usage:
    python scraper_simple.py

Output:
    output/linkedin_{timestamp}/
    ├── cookies.json
    ├── requests.har
    ├── page_1_https_www.linkedin.com_feed.html
    ├── page_2_https_www.linkedin.com_in_username.html
    └── page_3_...html
"""

from browser_use import Agent, ChatOpenAI, BrowserSession
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import asyncio
import os
import json
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional
import logging

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

class ScraperConfig:
    """Scraper configuration."""
    STORAGE_STATE_FILE = "linkedin_auth_state.json"
    OUTPUT_BASE_DIR = "output"
    CDP_PORT = 9222
    VIEWPORT_WIDTH = 1280
    VIEWPORT_HEIGHT = 720

    CHROME_ARGS = [
        '--remote-debugging-port=9222',
        '--disable-blink-features=AutomationControlled',
        '--disable-extensions',
        '--disable-component-extensions-with-background-pages',
        '--disable-default-apps',
        '--disable-background-networking',
        '--disable-sync',
        '--no-default-browser-check',
        '--no-first-run',
    ]

    MAX_AGENT_STEPS = 50
    MAX_FAILURES = 5
    LLM_MODEL = "grok-4-fast-non-reasoning"
    LLM_TEMPERATURE = 0.7


# ============================================================================
# DUMMY MODEL (required by browser-use but not used)
# ============================================================================

class DummyOutput(BaseModel):
    """Dummy output model since we're not extracting structured data."""
    status: str = Field(default="completed", description="Task status")


# ============================================================================
# AGENT TASKS
# ============================================================================

AUTHENTICATED_TASK = """
You are already logged into LinkedIn. Browse the profile and experience sections.

Steps:
1. Use navigate action to go to https://www.linkedin.com/feed/
2. Wait 3 seconds for the page to fully load
3. Look for the "Me" button/icon in the top navigation bar
4. Click the "Me" button to open the profile dropdown menu
5. In the dropdown, click "View Profile" link to go to your profile page
6. Wait 3 seconds for profile page to load
7. Scroll down slowly to load the Experience section
8. Wait 2 seconds
9. Continue scrolling down to find the Licenses & Certifications section
10. Wait 2 seconds
11. Use done action to complete

IMPORTANT:
- Do NOT navigate directly to profile URLs. Use UI navigation.
- Scroll slowly to ensure all sections load properly.
"""

LOGIN_TASK = """
Login to LinkedIn and browse the profile.

Steps:
1. Use navigate action to go to https://www.linkedin.com/login
2. Fill in the email field with {email} from sensitive_data
3. Fill in the password field with {password} from sensitive_data
4. Click the Sign in button
5. Wait 5 seconds for the page to load
6. If you see a verification prompt, STOP and wait for manual verification
7. After successful login, you should be on the feed page
8. Wait 3 seconds for feed to fully load
9. Look for the "Me" button/icon in the top right navigation
10. Click the "Me" button to open the profile dropdown menu
11. In the dropdown menu, click the "View Profile" link
12. Wait 3 seconds for profile page to load
13. Scroll down slowly to load the Experience section
14. Wait 2 seconds
15. Continue scrolling down to find the Licenses & Certifications section
16. Wait 2 seconds
17. Use done action to complete

IMPORTANT:
- Use credentials from sensitive_data dictionary.
- Do NOT navigate directly to profile URLs.
- Use UI navigation: Me button → View Profile.
"""


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def fix_storage_state_cookies(storage_state: dict) -> dict:
    """Fix cookie format for Playwright compatibility."""
    if 'cookies' not in storage_state:
        return storage_state

    fixed_cookies = []
    for cookie in storage_state['cookies']:
        fixed_cookie = cookie.copy()
        if 'partitionKey' in fixed_cookie:
            partition = fixed_cookie['partitionKey']
            if not isinstance(partition, str):
                del fixed_cookie['partitionKey']
        fixed_cookies.append(fixed_cookie)

    storage_state['cookies'] = fixed_cookies
    return storage_state


def clean_har_file(har_path: Path) -> tuple[int, int]:
    """Remove noise from HAR file."""
    with open(har_path, 'r', encoding='utf-8') as f:
        har_data = json.load(f)

    original_count = len(har_data.get('log', {}).get('entries', []))
    filtered_entries = []

    for entry in har_data.get('log', {}).get('entries', []):
        url = entry.get('request', {}).get('url', '')
        if any(url.startswith(prefix) for prefix in ['chrome-extension://', 'chrome://', 'about:']):
            continue
        filtered_entries.append(entry)

    har_data['log']['entries'] = filtered_entries
    with open(har_path, 'w', encoding='utf-8') as f:
        json.dump(har_data, f, indent=2)

    return original_count, len(filtered_entries)


def validate_har_completeness(har_path: Path) -> dict:
    """Validate HAR file has response bodies."""
    with open(har_path, 'r', encoding='utf-8') as f:
        har_data = json.load(f)

    entries = har_data.get('log', {}).get('entries', [])
    stats = {
        'total_entries': len(entries),
        'with_response_body': 0,
        'with_json_response': 0,
        'total_response_size': 0,
    }

    for entry in entries:
        response = entry.get('response', {})
        content = response.get('content', {})
        mime_type = content.get('mimeType', '')
        text = content.get('text', '')

        if text:
            stats['with_response_body'] += 1
            stats['total_response_size'] += len(text)
            if 'json' in mime_type.lower() or 'javascript' in mime_type.lower():
                stats['with_json_response'] += 1

    return stats


class HTMLCapture:
    """Captures HTML for every page navigation."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.page_counter = 0
        self.captured_urls = set()

    async def capture_page(self, page, url: str):
        """Capture HTML from a page."""
        # Avoid duplicates
        if url in self.captured_urls:
            return

        self.captured_urls.add(url)
        self.page_counter += 1

        try:
            html_content = await page.content()

            # Create safe filename
            safe_url = url.replace('://', '_').replace('/', '_').replace('?', '_').replace('&', '_')[:80]
            filename = f"page_{self.page_counter}_{safe_url}.html"
            file_path = self.output_dir / filename

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            logger.info(f"Captured HTML: {filename}")
            return file_path
        except Exception as e:
            logger.warning(f"Failed to capture HTML for {url}: {e}")
            return None


# ============================================================================
# MAIN SCRAPER
# ============================================================================

async def main():
    """Main scraper execution."""

    # Setup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"{ScraperConfig.OUTPUT_BASE_DIR}/linkedin_{timestamp}").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    har_file_path = output_dir / "requests.har"
    has_saved_auth = Path(ScraperConfig.STORAGE_STATE_FILE).exists()

    # Get credentials
    linkedin_email = os.getenv("LINKEDIN_EMAIL")
    linkedin_password = os.getenv("LINKEDIN_PASSWORD")

    if not has_saved_auth and (not linkedin_email or not linkedin_password):
        logger.error("No saved authentication and no credentials found!")
        logger.error("Please set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in your .env file")
        return

    logger.info(f"Output directory: {output_dir}")
    logger.info(f"HAR file: {har_file_path}")

    playwright_instance = None
    browser = None
    context = None
    html_capture = HTMLCapture(output_dir)

    try:
        # ====================================================================
        # STEP 1: Launch Playwright with HAR Recording
        # ====================================================================
        logger.info("Launching browser with HAR recording...")
        playwright_instance = await async_playwright().start()

        browser = await playwright_instance.chromium.launch(
            headless=False,
            args=ScraperConfig.CHROME_ARGS
        )

        context_options = {
            "record_har_path": str(har_file_path),
            "record_har_content": "embed",
            "record_har_mode": "full",
            "viewport": {
                "width": ScraperConfig.VIEWPORT_WIDTH,
                "height": ScraperConfig.VIEWPORT_HEIGHT
            },
        }

        # Load authentication if available
        if has_saved_auth:
            logger.info("Loading saved authentication...")
            with open(ScraperConfig.STORAGE_STATE_FILE, 'r') as f:
                storage_state = json.load(f)
            storage_state = fix_storage_state_cookies(storage_state)
            temp_storage_file = output_dir / "temp_storage_state.json"
            with open(temp_storage_file, 'w') as f:
                json.dump(storage_state, f, indent=2)
            context_options["storage_state"] = str(temp_storage_file)

        context = await browser.new_context(**context_options)
        page = await context.new_page()

        # Set up page navigation listener to capture HTML
        async def handle_navigation(frame):
            if frame == page.main_frame:
                await asyncio.sleep(2)  # Wait for page to render
                await html_capture.capture_page(page, page.url)

        page.on("framenavigated", handle_navigation)

        logger.info("Browser launched successfully")

        # ====================================================================
        # STEP 2: Connect browser-use Agent
        # ====================================================================
        logger.info("Connecting browser-use Agent...")

        cdp_url = f"http://localhost:{ScraperConfig.CDP_PORT}"
        browser_session = BrowserSession(cdp_url=cdp_url)

        llm = ChatOpenAI(
            model=ScraperConfig.LLM_MODEL,
            api_key=os.getenv("XAI_API_KEY"),
            base_url="https://api.x.ai/v1",
            temperature=ScraperConfig.LLM_TEMPERATURE,
            frequency_penalty=None,
        )

        sensitive_data = {}
        if not has_saved_auth:
            sensitive_data = {
                "email": linkedin_email,
                "password": linkedin_password,
            }

        task = AUTHENTICATED_TASK if has_saved_auth else LOGIN_TASK

        # ====================================================================
        # STEP 3: Run AI Agent
        # ====================================================================
        logger.info("Starting scraper agent...")

        agent = Agent(
            task=task,
            llm=llm,
            browser_session=browser_session,
            use_judge=False,
            sensitive_data=sensitive_data,
            max_failures=ScraperConfig.MAX_FAILURES,
            output_model_schema=DummyOutput,
        )

        history = await agent.run(max_steps=ScraperConfig.MAX_AGENT_STEPS)

        logger.info("Agent execution completed")

        # ====================================================================
        # STEP 4: Save Authentication State
        # ====================================================================
        if not has_saved_auth:
            logger.info("Saving authentication state...")
            try:
                storage_state = await context.storage_state()
                with open(ScraperConfig.STORAGE_STATE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(storage_state, f, indent=2)
                logger.info("Authentication saved successfully")
            except Exception as e:
                logger.warning(f"Could not save auth state: {e}")

        # ====================================================================
        # STEP 5: Save Cookies
        # ====================================================================
        logger.info("Extracting cookies...")
        all_cookies = await context.cookies()
        cookies_file = output_dir / "cookies.json"
        with open(cookies_file, 'w', encoding='utf-8') as f:
            json.dump(all_cookies, f, indent=2)
        logger.info(f"Saved {len(all_cookies)} cookies")

        # ====================================================================
        # STEP 6: Capture Final Page HTML (if not already captured)
        # ====================================================================
        logger.info("Capturing final page HTML...")
        if page.url not in html_capture.captured_urls:
            await html_capture.capture_page(page, page.url)

        # ====================================================================
        # STEP 7: Finalize HAR File
        # ====================================================================
        logger.info("Finalizing HAR file...")
        await context.close()
        await browser.close()
        await asyncio.sleep(1)

        # Clean HAR
        logger.info("Cleaning HAR file...")
        original_count, filtered_count = clean_har_file(har_file_path)
        removed = original_count - filtered_count
        if removed > 0:
            logger.info(f"Removed {removed} noise entries, kept {filtered_count} requests")

        # Validate HAR
        logger.info("Validating HAR completeness...")
        har_stats = validate_har_completeness(har_file_path)
        logger.info(f"HAR: {har_stats['with_response_body']}/{har_stats['total_entries']} entries with response bodies")
        logger.info(f"JSON responses: {har_stats['with_json_response']} entries")

        # ====================================================================
        # SUMMARY
        # ====================================================================
        print("\n" + "="*70)
        print("✅ SCRAPING COMPLETE")
        print("="*70)
        print(f"📁 Output directory: {output_dir}")
        print()

        # HAR file
        if har_file_path.exists():
            har_size = har_file_path.stat().st_size
            print("📦 HAR File: ✅ CREATED & VALIDATED")
            print(f"   Location: {har_file_path.name}")
            print(f"   Size: {har_size:,} bytes ({har_size / 1024 / 1024:.2f} MB)")
            print(f"   Entries: {har_stats['total_entries']} requests")
            print(f"   With Response Bodies: {har_stats['with_response_body']} ({har_stats['with_response_body']/har_stats['total_entries']*100:.1f}%)")
            print(f"   JSON Responses: {har_stats['with_json_response']}")
            print(f"   Response Data: {har_stats['total_response_size'] / 1024 / 1024:.2f} MB")
        else:
            print("📦 HAR File: ⚠️  NOT CREATED")

        print()

        # Cookies
        print(f"🍪 Cookies: {len(all_cookies)} cookies saved → cookies.json")
        print()

        # HTML files
        print(f"📄 HTML Files: {html_capture.page_counter} pages captured")
        for i in range(1, html_capture.page_counter + 1):
            html_files = list(output_dir.glob(f"page_{i}_*.html"))
            if html_files:
                print(f"   {i}. {html_files[0].name}")

        print("="*70)
        print("\n🎉 SUCCESS! Captured:")
        print("   ✅ 1x cookies.json - All browser cookies")
        print("   ✅ 1x requests.har - Complete network traffic with responses")
        print(f"   ✅ {html_capture.page_counter}x page_*.html - HTML for every page visited")
        print()

    except Exception as e:
        logger.error(f"Scraper failed: {e}", exc_info=True)
        raise

    finally:
        # Cleanup
        logger.info("Cleaning up resources...")

        if context:
            try:
                if not context._impl_obj._is_closed_or_closing:
                    await context.close()
            except Exception as e:
                logger.debug(f"Exception closing context: {e}")

        if browser:
            try:
                if browser.is_connected():
                    await browser.close()
            except Exception as e:
                logger.debug(f"Exception closing browser: {e}")

        if playwright_instance:
            try:
                await playwright_instance.stop()
            except Exception as e:
                logger.debug(f"Exception stopping Playwright: {e}")

        logger.info("Cleanup complete")


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    asyncio.run(main())
