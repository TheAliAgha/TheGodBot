import requests

text = "Bitcoin price rises above $70,000 as ETF inflows surge."
apis = [
    "https://translate.astian.org/translate",
    "https://libretranslate.com/translate",
    "https://translate.argosopentech.com/translate"
]

for api in apis:
    try:
        print(f"\n🔗 Testing {api}")
        res = requests.post(api, json={"q": text, "source": "en", "target": "fa"}, timeout=15)
        print("✅ Status:", res.status_code)
        print("Response:", res.text[:300])
    except Exception as e:
        print("❌ Error:", e)
