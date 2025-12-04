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

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS
# ============================================================================

class WorkExperience(BaseModel):
    """Represents a single work experience entry."""
    title: str = Field(description="Job title")
    company: str = Field(description="Company name")
    duration: str = Field(description="Employment duration")
    location: Optional[str] = Field(default=None, description="Work location")
    description: Optional[str] = Field(default=None, description="Job description")


class Certificate(BaseModel):
    """Represents a professional certificate or license."""
    name: str = Field(description="Certificate name")
    issuer: str = Field(description="Issuing organization")
    issue_date: Optional[str] = Field(default=None, description="Issue date")
    credential_id: Optional[str] = Field(default=None, description="Credential ID")
    credential_url: Optional[str] = Field(default=None, description="Credential URL")


class LinkedInProfile(BaseModel):
    """Complete LinkedIn profile data structure."""
    full_profile_name: str = Field(description="Full name")
    professional_headline: str = Field(description="Professional headline")
    number_of_connections: int = Field(description="Connection count")
    experience: list[WorkExperience] = Field(default_factory=list, description="Work history")
    certificates: list[Certificate] = Field(default_factory=list, description="Certifications")


# ============================================================================
# CONFIGURATION
# ============================================================================

class ScraperConfig:
    """Scraper configuration settings."""

    # Paths
    STORAGE_STATE_FILE = "linkedin_auth_state.json"
    OUTPUT_BASE_DIR = "output"

    # Browser settings
    CDP_PORT = 9222
    VIEWPORT_WIDTH = 1280
    VIEWPORT_HEIGHT = 720

    # Chrome launch arguments
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

    # Agent settings
    MAX_AGENT_STEPS = 50
    MAX_FAILURES = 5

    # LLM settings
    LLM_MODEL = "grok-4-fast-non-reasoning"
    LLM_TEMPERATURE = 0.7


# ============================================================================
# AGENT TASKS
# ============================================================================

AUTHENTICATED_TASK = """
You are already logged into LinkedIn.

Steps:
1. Use navigate action to go to https://www.linkedin.com/feed/
2. Wait 3 seconds for the page to fully load
3. Look for the "Me" button/icon in the top navigation bar
4. Click the "Me" button to open the profile dropdown menu
5. In the dropdown, click "View Profile" link to go to your profile page
6. Wait 3 seconds for profile page to load
7. Use extract action to get: profile name, headline, and number of connections
8. Scroll down slowly to load the Experience section
9. Use extract action to get all work experiences with: job title, company, duration, location, description
10. Continue scrolling down to find the Licenses & Certifications section
11. Use extract action to get all certificates with: name, issuer, issue date, credential ID, URL
12. Use done action with all extracted information

IMPORTANT:
- Do NOT navigate directly to profile URLs. Use UI navigation (Me button → View Profile)
- Scroll slowly to ensure all sections load properly
- Extract ALL experiences and certificates
- If a section is not visible, return empty lists
"""

LOGIN_TASK = """
Login to LinkedIn and extract profile information.

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
13. Use extract action to get: profile name, headline, and number of connections
14. Scroll down slowly to load the Experience section
15. Use extract action to get all work experiences with: job title, company, duration, location, description
16. Continue scrolling down to find the Licenses & Certifications section
17. Use extract action to get all certificates with: name, issuer, issue date, credential ID, URL
18. Use done action with all extracted information

IMPORTANT:
- Use credentials from sensitive_data dictionary
- Do NOT navigate directly to profile URLs
- Use UI navigation: Me button → View Profile dropdown link
- The "Me" button is in the TOP NAVIGATION BAR
- Scroll slowly to ensure all sections load properly
- Extract ALL experiences and certificates
- If a section is not visible, return empty lists
"""


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def fix_storage_state_cookies(storage_state: dict) -> dict:
    """
    Fix cookie format for Playwright compatibility.

    browser-use saves cookies with partitionKey as object,
    but Playwright expects string. This function removes incompatible fields.

    Args:
        storage_state: Storage state from browser-use

    Returns:
        Fixed storage state compatible with Playwright
    """
    if 'cookies' not in storage_state:
        return storage_state

    fixed_cookies = []
    for cookie in storage_state['cookies']:
        fixed_cookie = cookie.copy()

        # Remove partitionKey if it's not a string
        if 'partitionKey' in fixed_cookie:
            partition = fixed_cookie['partitionKey']
            if not isinstance(partition, str):
                del fixed_cookie['partitionKey']

        fixed_cookies.append(fixed_cookie)

    storage_state['cookies'] = fixed_cookies
    return storage_state


def clean_har_file(har_path: Path) -> tuple[int, int]:
    """
    Remove noise from HAR file (chrome extensions, internal URLs).

    Args:
        har_path: Path to HAR file

    Returns:
        Tuple of (original_count, filtered_count)
    """
    with open(har_path, 'r', encoding='utf-8') as f:
        har_data = json.load(f)

    original_count = len(har_data.get('log', {}).get('entries', []))
    filtered_entries = []

    for entry in har_data.get('log', {}).get('entries', []):
        url = entry.get('request', {}).get('url', '')

        # Skip noise URLs
        if any(url.startswith(prefix) for prefix in ['chrome-extension://', 'chrome://', 'about:']):
            continue

        filtered_entries.append(entry)

    # Update and save
    har_data['log']['entries'] = filtered_entries
    with open(har_path, 'w', encoding='utf-8') as f:
        json.dump(har_data, f, indent=2)

    return original_count, len(filtered_entries)


def print_profile_summary(profile: LinkedInProfile) -> None:
    """Print formatted profile summary."""
    print("\n📊 Extracted Profile Data:")
    print(f"   Name:        {profile.full_profile_name}")
    print(f"   Headline:    {profile.professional_headline}")
    print(f"   Connections: {profile.number_of_connections}")

    print(f"\n   Experience ({len(profile.experience)} positions):")
    for i, exp in enumerate(profile.experience, 1):
        print(f"      {i}. {exp.title} at {exp.company}")
        print(f"         Duration: {exp.duration}")
        if exp.location:
            print(f"         Location: {exp.location}")

    print(f"\n   Certificates ({len(profile.certificates)} certificates):")
    for i, cert in enumerate(profile.certificates, 1):
        print(f"      {i}. {cert.name}")
        print(f"         Issuer: {cert.issuer}")
        if cert.issue_date:
            print(f"         Issued: {cert.issue_date}")


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
    logger.info(f"HAR file will be saved to: {har_file_path}")

    playwright_instance = None
    browser = None
    context = None

    try:
        # ====================================================================
        # STEP 1: Launch Playwright with HAR Recording
        # ====================================================================
        logger.info("Launching Playwright browser with HAR recording...")
        playwright_instance = await async_playwright().start()

        browser = await playwright_instance.chromium.launch(
            headless=False,
            args=ScraperConfig.CHROME_ARGS
        )

        # Configure context with HAR recording
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
            logger.info("Loading saved authentication state...")

            with open(ScraperConfig.STORAGE_STATE_FILE, 'r') as f:
                storage_state = json.load(f)

            # Fix cookie format
            storage_state = fix_storage_state_cookies(storage_state)

            # Save to temp file
            temp_storage_file = output_dir / "temp_storage_state.json"
            with open(temp_storage_file, 'w') as f:
                json.dump(storage_state, f, indent=2)

            context_options["storage_state"] = str(temp_storage_file)

        context = await browser.new_context(**context_options)
        page = await context.new_page()

        logger.info("Browser launched with HAR recording enabled")

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

        # Prepare sensitive data
        sensitive_data = {}
        if not has_saved_auth:
            sensitive_data = {
                "email": linkedin_email,
                "password": linkedin_password,
            }

        # Select task
        task = AUTHENTICATED_TASK if has_saved_auth else LOGIN_TASK

        # ====================================================================
        # STEP 3: Run AI Agent
        # ====================================================================
        logger.info("Starting LinkedIn scraper agent...")

        agent = Agent(
            task=task,
            llm=llm,
            browser_session=browser_session,
            use_judge=False,
            sensitive_data=sensitive_data,
            max_failures=ScraperConfig.MAX_FAILURES,
            output_model_schema=LinkedInProfile,
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
        # STEP 5: Extract and Save Data
        # ====================================================================

        # Cookies
        logger.info("Extracting cookies...")
        all_cookies = await context.cookies()
        cookies_file = output_dir / "cookies.json"
        with open(cookies_file, 'w', encoding='utf-8') as f:
            json.dump(all_cookies, f, indent=2)
        logger.info(f"Saved {len(all_cookies)} cookies")

        # HTML
        logger.info("Extracting HTML...")
        pages = context.pages
        if pages:
            current_page = pages[0]
            current_html = await current_page.content()
            current_url = current_page.url

            safe_filename = current_url.replace('://', '_').replace('/', '_')[:100]
            html_file = output_dir / f"page_current_{safe_filename}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(current_html)
            logger.info(f"Saved HTML: {html_file.name}")

        # URLs
        visited_urls = history.urls()
        urls_file = output_dir / "visited_urls.json"
        with open(urls_file, 'w', encoding='utf-8') as f:
            json.dump(visited_urls, f, indent=2)

        # Structured profile data
        logger.info("Saving extracted content...")
        final_result = history.final_result()

        if final_result:
            profile = LinkedInProfile.model_validate_json(final_result)

            # Save JSON
            extracted_file = output_dir / "extracted_content.json"
            with open(extracted_file, 'w', encoding='utf-8') as f:
                json.dump(profile.model_dump(), f, indent=2, ensure_ascii=False)

            # Print summary
            print_profile_summary(profile)

            # Save extraction history
            history_file = output_dir / "extraction_history.json"
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(history.extracted_content(), f, indent=2, ensure_ascii=False)

            logger.info("All data saved successfully")
        else:
            logger.warning("No final result available from agent")

        # ====================================================================
        # STEP 6: Finalize HAR File
        # ====================================================================
        logger.info("Finalizing HAR file...")
        await context.close()
        await browser.close()
        await asyncio.sleep(1)

        # Clean HAR file
        logger.info("Cleaning HAR file...")
        original_count, filtered_count = clean_har_file(har_file_path)
        removed = original_count - filtered_count
        if removed > 0:
            logger.info(f"Removed {removed} noise entries, kept {filtered_count} LinkedIn requests")

        # ====================================================================
        # SUMMARY
        # ====================================================================
        print("\n" + "="*70)
        print("✅ LINKEDIN SCRAPING COMPLETE")
        print("="*70)
        print(f"📁 Output directory: {output_dir}")

        if har_file_path.exists():
            har_size = har_file_path.stat().st_size
            print("📦 HAR file: ✅ CREATED")
            print(f"   Location: {har_file_path}")
            print(f"   Size: {har_size:,} bytes ({har_size / 1024 / 1024:.2f} MB)")
            print(f"   Entries: {filtered_count} network requests")
        else:
            print("📦 HAR file: ⚠️  NOT CREATED")

        print(f"🍪 Cookies: {len(all_cookies)} saved")
        print(f"📄 HTML: Saved")
        print(f"🔗 URLs: {len(visited_urls)} visited")
        print("="*70)
        print("\n🎉 SUCCESS! All data captured:")
        print("   ✅ HAR file with complete network traffic")
        print("   ✅ All cookies")
        print("   ✅ Complete HTML")
        print("   ✅ Structured JSON data (profile, experience, certificates)")

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
