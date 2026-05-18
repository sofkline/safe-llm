# test_user.py
import openai
client = openai.OpenAI(api_key="sk-1234", base_url="http://localhost:30000")
r = client.chat.completions.create(
    model="gemma3-vpn1",
    user="sonya",
    messages=[{"role": "user", "content": "hello this is a test"}]
)
print(r.choices[0].message.content)