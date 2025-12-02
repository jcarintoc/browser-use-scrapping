from browser_use import Agent, ChatOpenAI, Browser
from dotenv import load_dotenv
import asyncio
import os
import json
from pathlib import Path

load_dotenv()


async def main():
    # Create output directory
    output_dir = "output"
    Path(output_dir).mkdir(exist_ok=True)

    # Configure browser to record HAR file (requests + responses)
    browser = Browser(
        record_har_path=f"{output_dir}/requests.har",  # Save all requests/responses
        record_har_content="embed",  # Include response bodies
        record_har_mode="full",  # Full recording mode
        headless=False,  # Show browser
        keep_alive=True,  # Keep browser alive after agent completes
    )

    # Use Grok model via browser-use's ChatOpenAI wrapper
    llm = ChatOpenAI(
        model="grok-4-fast-non-reasoning",  # Grok 4.1 Fast (non-reasoning)
        api_key=os.getenv("XAI_API_KEY"),
        base_url="https://api.x.ai/v1",
        temperature=0.7,
        frequency_penalty=None,  # Grok doesn't support this parameter
    )

    task = """
  Navigate to httpbin.org and complete these steps:
  1. Use navigate action to go to https://httpbin.org/cookies/set?session=test123&user=alice
  2. Wait 2 seconds for cookies to be set
  3. Use navigate action to go to https://httpbin.org/cookies to verify cookies
  4. Use extract action to get all cookie information displayed
  5. Use navigate action to https://httpbin.org/html to see HTML content
  6. Use extract action with query "page title and main heading"
  7. Use done action with all extracted information
  """

    # Run agent with configured browser
    agent = Agent(task=task, llm=llm, browser=browser, use_judge=False)
    history = await agent.run()

    # Access the browser session from the agent (from docs: agent.browser_session)
    browser_session = agent.browser_session

    # Save cookies after execution
    all_cookies = []
    try:
        # Access CDP session to get cookies
        cdp_session = await browser_session.get_or_create_cdp_session()

        # Get cookies using CDP Network.getCookies
        cookie_result = await cdp_session.cdp_client.send.Network.getCookies(
            session_id=cdp_session.session_id
        )
        all_cookies = cookie_result.get('cookies', [])
    except Exception as e:
        print(f"⚠️ Could not extract cookies: {e}")

    cookies_file = f"{output_dir}/cookies.json"
    with open(cookies_file, 'w') as f:
        json.dump(all_cookies, indent=2, fp=f)

    # Save HTML using CDP (from docs: get_or_create_cdp_session)
    page_count = 0
    try:
        cdp_session = await browser_session.get_or_create_cdp_session()

        # Get page HTML content using CDP
        doc = await cdp_session.cdp_client.send.DOM.getDocument(session_id=cdp_session.session_id)
        html_result = await cdp_session.cdp_client.send.DOM.getOuterHTML(
            params={'nodeId': doc['root']['nodeId']},
            session_id=cdp_session.session_id
        )
        page_html = html_result['outerHTML']

        # Get current state for URL
        state = await browser_session.get_browser_state_summary()
        url = state.url
        page_count = 1

        safe_filename = url.replace('://', '_').replace('/', '_')[:80]
        html_file = f"{output_dir}/page_{page_count}_{safe_filename}.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(page_html)
    except Exception as e:
        print(f"⚠️ Could not extract HTML: {e}")

    print("\n" + "="*60)
    print("✅ RECORDING COMPLETE")
    print("="*60)
    print(f"📁 HAR file (requests+responses): {output_dir}/requests.har")
    print(f"🍪 Cookies: {cookies_file} ({len(all_cookies)} cookies)")
    print(f"📄 HTML files: {page_count} page(s) saved")
    print(f"📊 URLs visited: {', '.join(history.urls())}")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
