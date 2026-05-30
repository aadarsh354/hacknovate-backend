import os
import json
import requests
import tldextract
import urllib3
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI

# 1. Configuration & Setup
load_dotenv()
app = Flask(__name__)
CORS(app) # Allows your frontend to talk to this backend safely

API_KEY = os.getenv("OPENAI_API_KEY")

print("====================================")
if API_KEY is None:
    print("❌ CONFIG ERROR: OpenAI API Key is missing from your .env file!")
else:
    print(f"✅ CONFIG SUCCESS: API Key loaded securely.")
print("====================================")

client = OpenAI(api_key=API_KEY)

# Standard headers to prevent basic scraper blocking
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive"
}

# 2. Scraper Function (Bypasses Mac SSL issues)
def fetch_url(url):
    # This disables the annoying red warnings in your terminal about the Mac SSL bypass
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    target_url = url.strip()
    if not target_url.startswith(('http://', 'https://')):
        target_url = "https://" + target_url

    try:
        # verify=False is the magic fix for the Mac SSL block
        res = requests.get(target_url, headers=HEADERS, timeout=15, verify=False)
        if res.status_code == 200:
            return res.text
        print(f"⚠️ SCRAPER WARNING: Status code {res.status_code} received.")
        return None
    except requests.RequestException as e:
        print(f"❌ SCRAPER ERROR: {e}")
        return None

# 3. AI Processing Function
def query_llm(client, domain, text):
    # The default data we send if the scraper fails or OpenAI crashes
    fallback_name = tldextract.extract(domain).domain.capitalize()
    empty_fallback = {
        "website_name": fallback_name, "company_name": "N/A", "address": "N/A",
        "mobile_number": "N/A", "mail": [], "core_service": "N/A",
        "target_customer": "N/A", "probable_pain_point": "N/A", "outreach_opener": "N/A"
    }

    if not text:
        return empty_fallback

    sys_prompt = "Extract operational details strictly from the provided text. If missing, return 'N/A'. Do not hallucinate data. Output strictly matching the requested JSON schema."
    user_prompt = f"Domain: {domain}\nText: {text}\nSchema:\n{{\"website_name\": \"String\", \"company_name\": \"String or 'N/A'\", \"address\": \"String or 'N/A'\", \"mobile_number\": \"String or 'N/A'\", \"mail\": [\"Array of emails or []\"], \"core_service\": \"String\", \"target_customer\": \"String\", \"probable_pain_point\": \"String\", \"outreach_opener\": \"String\"}}"
    
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        print(f"❌ OPENAI ERROR: {e}")
        empty_fallback["core_service"] = f"API Error: {str(e)}"
        return empty_fallback

# 4. Main API Route
@app.route('/enrich', methods=['POST'])
def enrich_target():
    try:
        data = request.json or {}
        raw_url = data.get('url', '').strip()
        
        print("\n=== 🛰️ LIVE TRANSACTION START ===")
        print(f"1. URL from Frontend: '{raw_url}'")
        
        if not raw_url:
            return jsonify({"error": "URL is required"}), 400

        # Run the Scraper
        scraped_html = fetch_url(raw_url)
        visible_text = ""
        
        if scraped_html:
            print(f"2. Scraper successfully downloaded {len(scraped_html)} characters.")
            soup = BeautifulSoup(scraped_html, 'html.parser')
            # Strip out website code, we only want words
            for element in soup(["script", "style", "noscript", "header", "footer", "meta"]):
                element.decompose()
            # Grab the first 4000 characters to save AI tokens
            visible_text = soup.get_text(separator=' ', strip=True)[:4000] 
            print(f"3. Parsed text successfully ({len(visible_text)} chars).")
        else:
            print("⚠️ 2. Scraper returned empty. Passing empty string to fallback logic.")

        # Query the AI
        print("4. Processing payload through OpenAI...")
        ai_response = query_llm(client, raw_url, visible_text)
        
        print("✅ 5. Extraction complete. Sending data back to UI.")
        print("=== 🛰️ LIVE TRANSACTION END ===\n")
        
        return jsonify(ai_response) # This sends the data straight back to your frontend

    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# 5. Keep the server awake and listening!
if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')