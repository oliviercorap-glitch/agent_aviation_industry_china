import os, json
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com/v1"
)

try:
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "威海广泰 航空地面设备 最新新闻 2026年6月"}],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        max_tokens=1000,
        temperature=0.1,
    )
    print("STATUS: OK")
    print("FINISH REASON:", response.choices[0].finish_reason)
    content = response.choices[0].message.content
    print("CONTENT:", str(content)[:1000])
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
