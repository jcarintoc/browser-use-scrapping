from browser_use import Agent, ChatOpenAI, Browser
from dotenv import load_dotenv
import asyncio
import os
import json
from pathlib import Path
from datetime import datetime

load_dotenv()


class RealtimeScraper:
    """Scraper that captures HTML, cookies, and requests in real-time during navigation"""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.html_count = 0
        self.cookies_snapshots = []
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    async def capture_page_snapshot(self, browser_session, label: str = ""):
        """Capture current page HTML and cookies"""
        try:
            cdp_session = await browser_session.get_or_create_cdp_session()

            # Get current state
            state = await browser_session.get_browser_state_summary()
            current_url = state.url

            # Capture HTML
            doc = await cdp_session.cdp_client.send.DOM.getDocument(
                session_id=cdp_session.session_id
            )
            html_result = await cdp_session.cdp_client.send.DOM.getOuterHTML(
                params={'nodeId': doc['root']['nodeId']},
                session_id=cdp_session.session_id
            )
            html_content = html_result['outerHTML']

            # Save HTML
            self.html_count += 1
            safe_url = current_url.replace('://', '_').replace('/', '_').replace('?', '_').replace('&', '_')[:80]
            label_prefix = f"{label}_" if label else ""
            html_file = f"{self.output_dir}/html_{self.html_count:03d}_{label_prefix}{safe_url}.html"

            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)

            # Capture cookies
            cookie_result = await cdp_session.cdp_client.send.Network.getCookies(
                session_id=cdp_session.session_id
            )
            cookies = cookie_result.get('cookies', [])

            # Store snapshot info
            snapshot = {
                'timestamp': datetime.now().isoformat(),
                'sequence': self.html_count,
                'url': current_url,
                'label': label,
                'html_file': html_file,
                'cookies_count': len(cookies),
                'title': state.title if hasattr(state, 'title') else ''
            }

            self.cookies_snapshots.append({
                **snapshot,
                'cookies': cookies
            })

            print(f"📸 Snapshot {self.html_count}: {current_url} ({len(cookies)} cookies)")
            return snapshot

        except Exception as e:
            print(f"⚠️  Failed to capture snapshot: {e}")
            return None


async def main():
    # Create output directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"output/realtime_{timestamp}"

    scraper = RealtimeScraper(output_dir)

    # Configure browser with HAR recording
    browser = Browser(
        record_har_path=f"{output_dir}/requests.har",
        record_har_content="embed",  # Include response bodies
        record_har_mode="full",
        headless=False,
        keep_alive=True,
    )

    # Configure LLM
    llm = ChatOpenAI(
        model="grok-4-fast-non-reasoning",
        api_key=os.getenv("XAI_API_KEY"),
        base_url="https://api.x.ai/v1",
        temperature=0.7,
        frequency_penalty=None,
    )

    # Define scraping task (be specific and name actions directly)
    task = """
    Complete these browsing tasks:
    1. Use navigate action to go to https://httpbin.org
    2. Use navigate action to go to https://httpbin.org/html
    3. Use navigate action to go to https://httpbin.org/cookies/set?session=test123&user=alice
    4. Use navigate action to go to https://httpbin.org/cookies to verify cookies
    5. Use extract action to get the cookie information displayed
    6. Use done action to complete the task
    """

    try:
        # Create agent
        agent = Agent(task=task, llm=llm, browser=browser, use_judge=False)

        # Run agent with periodic snapshots
        print("\n🚀 Starting browser automation with real-time capture...\n")

        # Start the agent in a task so we can monitor it
        agent_task = asyncio.create_task(agent.run(max_steps=50))

        # Monitor and capture snapshots periodically
        snapshot_interval = 3  # seconds (wait after navigation)
        last_url = None
        snapshot_count = 0

        while not agent_task.done():
            await asyncio.sleep(snapshot_interval)

            try:
                # Check if agent has started and has browser_session
                if hasattr(agent, 'browser_session') and agent.browser_session:
                    state = await agent.browser_session.get_browser_state_summary()
                    current_url = state.url

                    # Capture snapshot if URL changed
                    if current_url != last_url and current_url:
                        snapshot_count += 1
                        await scraper.capture_page_snapshot(
                            agent.browser_session,
                            label=f"nav{snapshot_count}"
                        )
                        last_url = current_url
            except Exception as e:
                # Agent might not be ready yet or already finished
                pass

        # Wait for agent to complete
        history = await agent_task
        print("\n✅ Agent execution completed\n")

        # Capture final snapshot
        if agent.browser_session:
            print("📸 Capturing final snapshot...")
            await scraper.capture_page_snapshot(agent.browser_session, label="final")

        # Save all cookies snapshots
        print("\n💾 Saving cookies history...")
        cookies_file = f"{output_dir}/cookies_timeline.json"
        with open(cookies_file, 'w', encoding='utf-8') as f:
            json.dump(scraper.cookies_snapshots, f, indent=2)

        # Save final cookies only
        final_cookies_file = f"{output_dir}/cookies_final.json"
        if scraper.cookies_snapshots:
            final_cookies = scraper.cookies_snapshots[-1]['cookies']
            with open(final_cookies_file, 'w', encoding='utf-8') as f:
                json.dump(final_cookies, f, indent=2)

        # Save visited URLs
        visited_urls = history.urls()
        urls_file = f"{output_dir}/visited_urls.json"
        with open(urls_file, 'w', encoding='utf-8') as f:
            json.dump(visited_urls, f, indent=2)

        # Save metadata
        metadata = {
            'scrape_timestamp': timestamp,
            'total_snapshots': scraper.html_count,
            'total_urls_visited': len(visited_urls),
            'urls': visited_urls,
            'snapshots': [
                {k: v for k, v in s.items() if k != 'cookies'}
                for s in scraper.cookies_snapshots
            ]
        }
        metadata_file = f"{output_dir}/metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

        # === SUMMARY ===
        print("\n" + "="*70)
        print("✅ REAL-TIME SCRAPING COMPLETE")
        print("="*70)
        print(f"📁 Output directory: {output_dir}")
        print(f"\n📦 Captured Data:")
        print(f"   • HAR file: {output_dir}/requests.har")
        print(f"   • HTML snapshots: {scraper.html_count} files")
        print(f"   • Cookie timeline: {cookies_file}")
        print(f"   • Final cookies: {final_cookies_file}")
        print(f"   • URLs visited: {urls_file}")
        print(f"   • Metadata: {metadata_file}")
        print(f"\n🔗 URLs Visited ({len(visited_urls)}):")
        for i, url in enumerate(visited_urls, 1):
            print(f"   {i}. {url}")
        print("\n📸 Snapshots Captured:")
        for snapshot in scraper.cookies_snapshots:
            if 'cookies' in snapshot:
                del snapshot['cookies']  # Don't print full cookies
            print(f"   • {snapshot['sequence']:03d}: {snapshot['url'][:60]}")
        print("="*70)
        print("\n💡 Tips:")
        print("   • HAR file contains ALL requests/responses")
        print("   • cookies_timeline.json shows cookie changes over time")
        print("   • Each HTML file is numbered in order of capture")

    finally:
        # CRITICAL: Always clean up browser resources
        if 'browser' in locals():
            print("\n🧹 Cleaning up browser resources...")
            await browser.stop()
            print("✅ Browser stopped successfully")


if __name__ == "__main__":
    asyncio.run(main())
