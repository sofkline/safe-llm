import openai

client = openai.OpenAI(
    api_key="sk-g43_e2wlRF4Tmtqq6c0nTg",
    base_url="http://localhost:4000"
)

# Example with text only
response = client.chat.completions.create(
    model="gpt-5-nano",
    messages=[
        {
            "role": "user",
            "content": "hello"
        },
        {
            "role": "assistant",
            "content": "Hi there! How can I help today?\n\nI can do things like:\n- Explain concepts or answer questions\n- Draft or edit text (emails, essays, resumes)\n- Help with coding or math problems\n- Brainstorm ideas or plan projects\n- Translate or summarize\n- Analyze or describe images you provide\n\nTell me what you’d like to work on, and any preferences for tone or length. You can also share a specific question or task to get started."
        },
        {
            "role": "user",
            "content": "ho are u doing"
        },
    ],
    extra_body={
        "metadata": {
            "my_key": "my_value",
            "tags": ['classify: 5']
        }
    }
)

print(response)
