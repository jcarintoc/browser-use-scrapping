"""
LinkedIn Scraper with Secure Credential Handling

Best practices from browser-use docs:
1. Use 'sensitive_data' parameter to protect credentials from logs
2. Use 'storage_state' to save authentication (avoids re-entering credentials)
3. Credentials stored in .env file (never in code)
"""

from browser_use import Agent, ChatOpenAI, Browser
from dotenv import load_dotenv
import asyncio
import os
import json
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel

load_dotenv()


# Define structured output schema
class LinkedInProfile(BaseModel):
    full_profile_name: str
    professional_headline: str
    number_of_connections: int


async def main():
    # Create output directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"output/linkedin_{timestamp}"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Check if we have saved authentication state
    storage_state_file = "linkedin_auth_state.json"
    has_saved_auth = Path(storage_state_file).exists()

    # Get credentials from environment variables
    linkedin_email = os.getenv("LINKEDIN_EMAIL")
    linkedin_password = os.getenv("LINKEDIN_PASSWORD")

    if not has_saved_auth and (not linkedin_email or not linkedin_password):
        print("❌ ERROR: No saved authentication and no credentials found!")
        print("Please set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in your .env file")
        return

    # Configure browser (different setup for first-time login vs saved auth)
    browser_config = {
        "record_har_path": f"{output_dir}/requests.har",
        "record_har_content": "embed",
        "record_har_mode": "full",
        "headless": False,
        "keep_alive": True,
        # SECURITY: Lock down to LinkedIn domains only (protects sensitive_data from prompt injection)
        "allowed_domains": ["*.linkedin.com", "www.linkedin.com"],
    }

    # IMPORTANT: According to browser-use docs, you cannot use BOTH storage_state AND user_data_dir
    # Choose one approach based on whether we have saved auth
    if has_saved_auth:
        print("✅ Loading saved authentication state...")
        # Use storage_state WITHOUT user_data_dir (as per docs)
        browser_config["storage_state"] = storage_state_file
        # Explicitly set user_data_dir to None when using storage_state
        browser_config["user_data_dir"] = None
    else:
        print("⚠️  No saved auth found. Will perform login with credentials...")
        # Use user_data_dir WITHOUT storage_state for first login
        browser_config["user_data_dir"] = "./browser_data/linkedin_profile"
        # storage_state is not set (defaults to None)

    browser = Browser(**browser_config)

    # Configure LLM
    llm = ChatOpenAI(
        model="grok-4-fast-non-reasoning",
        api_key=os.getenv("XAI_API_KEY"),
        base_url="https://api.x.ai/v1",
        temperature=0.7,
        frequency_penalty=None,
    )

    # SENSITIVE DATA: This dictionary protects credentials from being logged
    # According to browser-use docs, this prevents credentials from appearing in logs/traces
    sensitive_data = {}
    if not has_saved_auth:
        sensitive_data = {
            "email": linkedin_email,
            "password": linkedin_password,
        }

    # Define task based on whether we need to login
    if has_saved_auth:
        # Skip login, already authenticated via storage_state
        task = """
        You are already logged into LinkedIn.
        1. Use navigate action to go to https://www.linkedin.com/feed/
        2. Wait 3 seconds for the page to fully load
        3. Look for the "Me" button/icon in the top navigation bar (usually shows your profile picture and name)
        4. Click the "Me" button to open the profile dropdown menu
        5. In the dropdown, click "View Profile" link to go to your profile page
        6. Wait 3 seconds for profile page to load
        7. Use extract action to get: profile name, headline, and number of connections
        8. Use done action with all extracted information

        IMPORTANT: Do NOT try to navigate directly to profile URLs. Use the UI navigation (Me button -> View Profile).
        """
    else:
        # Need to login first
        task = """
        Login to LinkedIn and extract profile information:
        1. Use navigate action to go to https://www.linkedin.com/login
        2. Fill in the email field with {email} from sensitive_data
        3. Fill in the password field with {password} from sensitive_data
        4. Click the Sign in button
        5. Wait 5 seconds for the page to load and verify login was successful
        6. If you see a verification prompt, STOP and wait for manual verification (keep_alive=True)
        7. After successful login, you should be on the feed page
        8. Wait 3 seconds for feed to fully load
        9. Look for the "Me" button/icon in the top right navigation (shows profile picture/name)
        10. Click the "Me" button to open the profile dropdown menu (NOT the messaging button!)
        11. In the dropdown menu, click the "View Profile" link
        12. Wait 3 seconds for profile page to load
        13. Use extract action to get: profile name, headline, and number of connections
        14. Use done action with all extracted information

        IMPORTANT:
        - Use credentials from sensitive_data dictionary, never type them manually
        - Do NOT try to navigate directly to profile URLs like /in/username
        - Use the UI navigation: Me button -> View Profile dropdown link
        - The "Me" button is in the TOP NAVIGATION BAR, not the messaging area
        """

    try:
        print("\n🚀 Starting LinkedIn scraper...\n")

        # Create agent with sensitive_data parameter (protects credentials)
        agent = Agent(
            task=task,
            llm=llm,
            browser=browser,
            use_judge=False,
            sensitive_data=sensitive_data,  # CRITICAL: Protects credentials from logs
            max_failures=5,  # LinkedIn may have challenges
            output_model_schema=LinkedInProfile,  # Enforce structured output
        )

        # Run agent
        history = await agent.run(max_steps=50)

        # Access browser session
        browser_session = agent.browser_session

        print("\n✅ Agent execution completed\n")

        # === SAVE AUTHENTICATION STATE for future runs ===
        if not has_saved_auth:
            print("💾 Saving authentication state for future runs...")
            try:
                # Get browser context and save storage state
                cdp_session = await browser_session.get_or_create_cdp_session()

                # Get cookies
                cookie_result = await cdp_session.cdp_client.send.Network.getCookies(
                    session_id=cdp_session.session_id
                )
                cookies = cookie_result.get('cookies', [])

                # Save storage state (cookies + localStorage)
                storage_state = {
                    'cookies': cookies,
                    'origins': []  # Could add localStorage here if needed
                }

                with open(storage_state_file, 'w', encoding='utf-8') as f:
                    json.dump(storage_state, f, indent=2)

                print(f"✅ Authentication saved to {storage_state_file}")
                print("   Next time, you won't need to enter credentials!")
            except Exception as e:
                print(f"⚠️  Could not save auth state: {e}")

        # === SAVE ALL COOKIES ===
        print("\n📝 Extracting cookies...")
        all_cookies = []
        try:
            cdp_session = await browser_session.get_or_create_cdp_session()
            cookie_result = await cdp_session.cdp_client.send.Network.getCookies(
                session_id=cdp_session.session_id
            )
            all_cookies = cookie_result.get('cookies', [])

            cookies_file = f"{output_dir}/cookies.json"
            with open(cookies_file, 'w', encoding='utf-8') as f:
                json.dump(all_cookies, f, indent=2)
            print(f"✅ Saved {len(all_cookies)} cookies to {cookies_file}")
        except Exception as e:
            print(f"⚠️  Failed to extract cookies: {e}")

        # === SAVE HTML FROM CURRENT PAGE ===
        print("\n📄 Extracting HTML from current page...")
        html_files_saved = 0

        try:
            cdp_session = await browser_session.get_or_create_cdp_session()

            # Save HTML from current page
            doc = await cdp_session.cdp_client.send.DOM.getDocument(
                session_id=cdp_session.session_id
            )
            html_result = await cdp_session.cdp_client.send.DOM.getOuterHTML(
                params={'nodeId': doc['root']['nodeId']},
                session_id=cdp_session.session_id
            )
            current_html = html_result['outerHTML']

            # Get current URL
            state = await browser_session.get_browser_state_summary()
            current_url = state.url

            # Save current page HTML
            safe_filename = current_url.replace('://', '_').replace('/', '_').replace('?', '_').replace('&', '_')[:100]
            html_file = f"{output_dir}/page_current_{safe_filename}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(current_html)
            html_files_saved += 1
            print(f"✅ Saved current page: {html_file}")

            # Save visited URLs
            visited_urls = history.urls()
            urls_file = f"{output_dir}/visited_urls.json"
            with open(urls_file, 'w', encoding='utf-8') as f:
                json.dump(visited_urls, f, indent=2)
            print(f"✅ Saved visited URLs list to {urls_file}")

        except Exception as e:
            print(f"⚠️  Failed to extract HTML: {e}")

        # === SAVE EXTRACTED CONTENT ===
        print("\n📊 Saving extracted content...")
        try:
            # Get final result and parse using Pydantic model
            final_result = history.final_result()

            if final_result:
                # Parse JSON result into Pydantic model
                parsed_profile: LinkedInProfile = LinkedInProfile.model_validate_json(final_result)

                # Convert to clean JSON dict
                profile_data = parsed_profile.model_dump()

                # Save clean structured data
                extracted_file = f"{output_dir}/extracted_content.json"
                with open(extracted_file, 'w', encoding='utf-8') as f:
                    json.dump(profile_data, f, indent=2, ensure_ascii=False)
                print(f"✅ Saved structured profile data to {extracted_file}")

                # Print the extracted data
                print("\n📊 Extracted Profile Data:")
                print(f"   Name:        {parsed_profile.full_profile_name}")
                print(f"   Headline:    {parsed_profile.professional_headline}")
                print(f"   Connections: {parsed_profile.number_of_connections}")
            else:
                print("⚠️  No final result available")

            # Optionally save full extraction history for debugging
            all_extracted = history.extracted_content()
            history_file = f"{output_dir}/extraction_history.json"
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(all_extracted, f, indent=2, ensure_ascii=False)
            print(f"📋 Saved full extraction history to {history_file}")
        except Exception as e:
            print(f"⚠️  Failed to save extracted content: {e}")
            import traceback
            traceback.print_exc()

        # === SUMMARY ===
        visited_urls = history.urls()
        print("\n" + "="*70)
        print("✅ LINKEDIN SCRAPING COMPLETE")
        print("="*70)
        print(f"📁 Output directory: {output_dir}")
        print(f"📦 HAR file (requests+responses): {output_dir}/requests.har")
        print(f"🍪 Cookies: {len(all_cookies)} cookies saved")
        print(f"📄 HTML files: {html_files_saved} page(s) saved")
        print(f"🔗 URLs visited: {len(visited_urls)}")
        for i, url in enumerate(visited_urls, 1):
            print(f"   {i}. {url}")
        print("="*70)
        print("\n💡 Security Tips:")
        print("   • Your credentials are protected via sensitive_data parameter")
        print("   • Authentication state saved - no need to re-enter credentials next time")
        print("   • HAR file contains ALL requests/responses for analysis")

    finally:
        # CRITICAL: Always clean up browser resources
        if 'browser' in locals():
            print("\n🧹 Cleaning up browser resources...")
            await browser.stop()
            print("✅ Browser stopped successfully")


if __name__ == "__main__":
    asyncio.run(main())
