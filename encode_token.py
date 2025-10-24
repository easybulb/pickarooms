import base64
import json

# Read token
with open('gmail_token.json', 'r') as f:
    token_data = f.read()

# Verify it's valid JSON
json.loads(token_data)
print("Token is valid JSON")

# Encode it
encoded = base64.b64encode(token_data.encode()).decode()
print("\nEncoded token:")
print(encoded)