from browser_use import Agent, ChatOpenAI, Browser
from dotenv import load_dotenv
import asyncio
import os
import json
from pathlib import Path
from datetime import datetime

load_dotenv()


async def main():
    # Create output directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"output/scrape_{timestamp}"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Configure browser to record HAR file with full request/response content
    browser = Browser(
        record_har_path=f"{output_dir}/requests.har",  # Save all requests/responses
        record_har_content="embed",  # Include response bodies in HAR
        record_har_mode="full",  # Full recording mode (not minimal)
        headless=False,  # Show browser for debugging
        keep_alive=True,  # Keep browser open after completion
    )

    # Configure LLM (using Grok model via X.AI)
    llm = ChatOpenAI(
        model="grok-4-fast-non-reasoning",
        api_key=os.getenv("XAI_API_KEY"),
        base_url="https://api.x.ai/v1",
        temperature=0.7,
        frequency_penalty=None,  # Grok doesn't support this parameter
    )

    # Define your scraping task (be specific and name actions directly)
    task = """
    Navigate to https://example.com and explore the site:
    1. Use navigate action to go to the main page
    2. Use extract action to get the page title and heading
    3. Click on "More information" link if available
    4. Use extract action to get content from that page
    5. Use done action to complete the task
    """

    try:
        # Run the agent with explicit max_steps
        agent = Agent(task=task, llm=llm, browser=browser, use_judge=False)
        history = await agent.run(max_steps=50)

        # Access browser session from the agent
        browser_session = agent.browser_session

        # === 1. SAVE ALL COOKIES ===
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

        # === 2. HAR FILE (already being recorded by Browser config) ===
        print(f"\n📦 HAR file recorded at: {output_dir}/requests.har")

        # === 3. SAVE HTML FROM ALL VISITED PAGES ===
        print("\n📄 Extracting HTML from all visited pages...")
        html_files_saved = 0

        # Get all unique URLs visited from history
        visited_urls = history.urls()
        print(f"   Found {len(visited_urls)} unique URLs in history")

        try:
            cdp_session = await browser_session.get_or_create_cdp_session()

            # Save HTML from current page (last visited)
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

            # For historical pages, we can try to navigate back and capture
            # (Note: This is optional - you may want to capture during navigation instead)
            # For now, we'll save the URLs list for reference
            urls_file = f"{output_dir}/visited_urls.json"
            with open(urls_file, 'w', encoding='utf-8') as f:
                json.dump(visited_urls, f, indent=2)
            print(f"✅ Saved visited URLs list to {urls_file}")

        except Exception as e:
            print(f"⚠️  Failed to extract HTML: {e}")

        # === SAVE AGENT HISTORY ===
        print("\n📊 Saving agent execution history...")
        try:
            # Save the agent's action history
            history_data = {
                'urls_visited': visited_urls,
                'total_actions': len(history.history),
                'model_actions': [
                    {
                        'step': i,
                        'action': str(action.model_output) if hasattr(action, 'model_output') else str(action),
                    }
                    for i, action in enumerate(history.history)
                ]
            }

            history_file = f"{output_dir}/agent_history.json"
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(history_data, f, indent=2)
            print(f"✅ Saved agent history to {history_file}")
        except Exception as e:
            print(f"⚠️  Failed to save history: {e}")

        # === SUMMARY ===
        print("\n" + "="*70)
        print("✅ SCRAPING COMPLETE")
        print("="*70)
        print(f"📁 Output directory: {output_dir}")
        print(f"📦 HAR file (requests+responses): {output_dir}/requests.har")
        print(f"🍪 Cookies: {len(all_cookies)} cookies saved")
        print(f"📄 HTML files: {html_files_saved} page(s) saved")
        print(f"🔗 URLs visited: {len(visited_urls)}")
        for i, url in enumerate(visited_urls, 1):
            print(f"   {i}. {url}")
        print("="*70)
        print("\n💡 Tip: The HAR file contains ALL requests and responses.")
        print("   You can import it into browser DevTools or HAR viewers for analysis.")

    finally:
        # CRITICAL: Always clean up browser resources
        if 'browser' in locals():
            print("\n🧹 Cleaning up browser resources...")
            await browser.stop()
            print("✅ Browser stopped successfully")


if __name__ == "__main__":
    asyncio.run(main())
