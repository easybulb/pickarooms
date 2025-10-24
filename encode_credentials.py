import base64

# Read credentials
with open('gmail_credentials.json', 'r') as f:
    creds_data = f.read()

# Encode it
encoded = base64.b64encode(creds_data.encode()).decode()
print("Encoded credentials:")
print(encoded)