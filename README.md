# 👋 Installation

**1. Create environment with [uv](https://docs.astral.sh/uv/) (Python>=3.11):**

```bash
pip install uv
uv venv --python 3.12
```

**2. Activate environment**

```bash
source .venv/bin/activate
# On Windows use `.venv\Scripts\activate`
```

**3. Install browser-use & chromium:**

```bash
uv pip install browser-use
uvx browser-use install
```

**4. Install playwright**

```bash
uv pip install playwright aiohttp
```

**5. Create .env and copy/paste .env.example**

```bash
OPENAI_API_KEY=
```

**6. Run main.py**

```bash
py main.py
```