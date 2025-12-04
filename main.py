from browser_use import Agent, ChatOpenAI, BrowserSession
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import asyncio
import os
import json
import argparse
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional
import logging

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

class ScraperConfig:
    """Default scraper configuration."""
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


class DummyOutput(BaseModel):
    """Dummy output for agent."""
    status: str = Field(default="completed", description="Task status")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def load_website_config(config_path: str) -> dict:
    """Load website-specific configuration from JSON file."""
    if not Path(config_path).exists():
        logger.error(f"Config file not found: {config_path}")
        logger.info("Creating template configuration files...")
        create_example_config()
        return None

    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def create_example_config():
    """Create example configuration files."""
    # Template with login (LinkedIn example)
    with_login = {
        "website_name": "linkedin",
        "description": "Scrape LinkedIn profile",
        "needs_login": True,
        "login_url": "https://www.linkedin.com/login",
        "credentials": {
            "email_env_var": "LINKEDIN_EMAIL",
            "password_env_var": "LINKEDIN_PASSWORD"
        },
        "allowed_domains": [
            "*.linkedin.com",
            "www.linkedin.com"
        ],
        "task": "Login to LinkedIn and navigate to profile:\n1. Use navigate action to go to https://www.linkedin.com/login\n2. Fill email field with {email} from sensitive_data\n3. Fill password field with {password} from sensitive_data\n4. Click Sign in button\n5. Wait 5 seconds for page to load\n6. Click the Me button in top navigation\n7. Click View Profile in dropdown menu\n8. Wait 3 seconds for profile to load\n9. Scroll down to load all sections\n10. Use done action when complete",
        "storage_state_file": "linkedin_auth_state.json"
    }

    # Template without login (Hacker News example)
    without_login = {
        "website_name": "hackernews",
        "description": "Scrape Hacker News front page",
        "needs_login": False,
        "task": "Browse Hacker News front page:\n1. Use navigate action to go to https://news.ycombinator.com\n2. Wait 2 seconds for page to load\n3. Scroll down to load more posts\n4. Wait 1 second\n5. Click on the first post to read comments\n6. Wait 2 seconds for comments to load\n7. Scroll down to see more comments\n8. Wait 1 second\n9. Use done action to complete"
    }

    # Create examples/templates directory
    templates_dir = Path('examples/templates')
    templates_dir.mkdir(parents=True, exist_ok=True)

    # Save both templates
    with_login_path = templates_dir / 'with_login_template.json'
    with open(with_login_path, 'w', encoding='utf-8') as f:
        json.dump(with_login, f, indent=2)

    without_login_path = templates_dir / 'without_login_template.json'
    with open(without_login_path, 'w', encoding='utf-8') as f:
        json.dump(without_login, f, indent=2)

    logger.info(f"✅ Created templates:")
    logger.info(f"   - {with_login_path} (with authentication)")
    logger.info(f"   - {without_login_path} (without authentication)")
    logger.info(f"\n💡 Copy a template to examples/ and edit for your website")


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
        if url in self.captured_urls:
            return

        self.captured_urls.add(url)
        self.page_counter += 1

        try:
            html_content = await page.content()
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

async def scrape_website(config: dict):
    """
    Scrape any website based on configuration.

    Args:
        config: Website configuration dictionary
    """
    website_name = config.get('website_name', 'website')
    needs_login = config.get('needs_login', False)
    storage_state_file = config.get('storage_state_file', f'{website_name}_auth_state.json')

    # Setup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"{ScraperConfig.OUTPUT_BASE_DIR}/{website_name}_{timestamp}").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    har_file_path = output_dir / "requests.har"
    has_saved_auth = Path(storage_state_file).exists() if needs_login else False

    # Get credentials if needed
    credentials = {}
    if needs_login and not has_saved_auth:
        creds_config = config.get('credentials', {})
        email_var = creds_config.get('email_env_var')
        password_var = creds_config.get('password_env_var')

        if email_var and password_var:
            email = os.getenv(email_var)
            password = os.getenv(password_var)

            if not email or not password:
                logger.error(f"Missing credentials! Set {email_var} and {password_var} in .env file")
                return

            credentials = {"email": email, "password": password}

    logger.info(f"Scraping: {website_name}")
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
            with open(storage_state_file, 'r') as f:
                storage_state = json.load(f)
            storage_state = fix_storage_state_cookies(storage_state)
            temp_storage_file = output_dir / "temp_storage_state.json"
            with open(temp_storage_file, 'w') as f:
                json.dump(storage_state, f, indent=2)
            context_options["storage_state"] = str(temp_storage_file)

        context = await browser.new_context(**context_options)
        page = await context.new_page()

        # Set up page navigation listener
        async def handle_navigation(frame):
            if frame == page.main_frame:
                await asyncio.sleep(2)
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

        # Get task from config
        task = config.get('task', 'Navigate the website and browse pages. Use done action when complete.')

        # Set allowed domains if specified
        allowed_domains = config.get('allowed_domains')

        # ====================================================================
        # STEP 3: Run AI Agent
        # ====================================================================
        logger.info("Starting scraper agent...")

        agent_config = {
            "task": task,
            "llm": llm,
            "browser_session": browser_session,
            "use_judge": False,
            "max_failures": ScraperConfig.MAX_FAILURES,
            "output_model_schema": DummyOutput,
        }

        if credentials:
            agent_config["sensitive_data"] = credentials

        agent = Agent(**agent_config)

        history = await agent.run(max_steps=ScraperConfig.MAX_AGENT_STEPS)

        logger.info("Agent execution completed")

        # ====================================================================
        # STEP 4: Save Authentication State
        # ====================================================================
        if needs_login and not has_saved_auth:
            logger.info("Saving authentication state...")
            try:
                storage_state = await context.storage_state()
                with open(storage_state_file, 'w', encoding='utf-8') as f:
                    json.dump(storage_state, f, indent=2)
                logger.info(f"Authentication saved to {storage_state_file}")
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
        # STEP 6: Capture Final Page HTML
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
            logger.info(f"Removed {removed} noise entries")

        # Validate HAR
        logger.info("Validating HAR completeness...")
        har_stats = validate_har_completeness(har_file_path)

        # ====================================================================
        # SUMMARY
        # ====================================================================
        print("\n" + "="*70)
        print(f"✅ {website_name.upper()} SCRAPING COMPLETE")
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
        else:
            print("📦 HAR File: ⚠️  NOT CREATED")

        print()
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
        print("   ✅ 1x cookies.json")
        print("   ✅ 1x requests.har")
        print(f"   ✅ {html_capture.page_counter}x page_*.html")
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
            except:
                pass

        if browser:
            try:
                if browser.is_connected():
                    await browser.close()
            except:
                pass

        if playwright_instance:
            try:
                await playwright_instance.stop()
            except:
                pass

        logger.info("Cleanup complete")


# ============================================================================
# CLI
# ============================================================================

async def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(description='Universal Web Scraper')
    parser.add_argument('--config', type=str, default='examples/scraper_config.json',
                       help='Path to configuration JSON file (default: examples/scraper_config.json)')
    args = parser.parse_args()

    # Load configuration
    config = load_website_config(args.config)
    if not config:
        logger.error("Could not load configuration. Exiting.")
        return

    # Run scraper
    await scrape_website(config)


if __name__ == "__main__":
    asyncio.run(main())
