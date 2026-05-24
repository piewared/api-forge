# OIDC Client Examples

This folder contains working examples of OIDC clients that authenticate with your API Forge backend.

## Examples

### Python OIDC Client

**File**: `python_oidc_client.py`

A complete Python implementation of an OIDC client using the Authorization Code Flow with PKCE.

**Features**:
- Authorization Code Flow with PKCE
- Automatic token refresh
- User info retrieval
- Authenticated API requests
- Complete example with local callback server

**Installation**:
```bash
pip install requests authlib
```

**Usage**:
```python
from python_oidc_client import APIForgeClient

# Initialize client
client = APIForgeClient(
    api_base_url="http://localhost:8000",
    client_id="your-client-id",
    redirect_uri="http://localhost:8080/callback",
    provider="google"
)

# Get authorization URL
auth_url, code_verifier = client.get_authorization_url()
print(f"Visit: {auth_url}")

# After user authorizes and you receive the code
tokens = client.exchange_code_for_tokens(code, code_verifier)

# Get user info
user_info = client.get_user_info()
print(f"User: {user_info['email']}")

# Make authenticated requests
response = client.make_authenticated_request("GET", "/api/users")
```

**Run the interactive example**:
```bash
python python_oidc_client.py
```

This will:
1. Start a local callback server on port 8080
2. Open your browser to the authorization URL
3. Handle the OAuth callback
4. Display user information and access token

---

### TypeScript OIDC Client

**File**: `typescript_oidc_client.ts`

A complete TypeScript/JavaScript implementation compatible with Node.js and browsers.

**Features**:
- Authorization Code Flow with PKCE
- Automatic token refresh with retry logic
- Type-safe API
- Axios-based HTTP client
- Token storage helpers

**Installation**:
```bash
npm install axios
npm install --save-dev @types/node  # For TypeScript
```

**Usage**:
```typescript
import { APIForgeClient } from './typescript_oidc_client';

// Initialize client
const client = new APIForgeClient(
  'http://localhost:8000',
  'your-client-id',
  'http://localhost:3000/callback',
  'google'
);

// Get authorization URL
const { authUrl, codeVerifier, state } = client.getAuthorizationUrl();
console.log('Visit:', authUrl);
// Store codeVerifier and state securely (e.g., sessionStorage)

// After user authorizes and you receive the code
const tokens = await client.exchangeCodeForTokens(code, codeVerifier);

// Get user info
const userInfo = await client.getUserInfo();
console.log('User:', userInfo.email);

// Make authenticated requests
const response = await client.makeAuthenticatedRequest('GET', '/api/users');

// Refresh token
if (client.getRefreshToken()) {
  await client.refreshAccessToken();
}

// Logout
await client.logout();
```

**Browser Usage**:

For browser environments, you can use this with a bundler like Webpack or Vite. Here's a React example:

```typescript
import { useEffect, useState } from 'react';
import { APIForgeClient } from './typescript_oidc_client';

function App() {
  const [client] = useState(() => new APIForgeClient(
    'http://localhost:8000',
    'your-client-id',
    window.location.origin + '/callback',
    'google'
  ));

  const handleLogin = () => {
    const { authUrl, codeVerifier, state } = client.getAuthorizationUrl();
    // Store for later
    sessionStorage.setItem('code_verifier', codeVerifier);
    sessionStorage.setItem('state', state);
    // Redirect to auth
    window.location.href = authUrl;
  };

  // Handle callback
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    
    if (code && state) {
      const storedVerifier = sessionStorage.getItem('code_verifier');
      const storedState = sessionStorage.getItem('state');
      
      if (state === storedState && storedVerifier) {
        client.exchangeCodeForTokens(code, storedVerifier)
          .then(tokens => {
            // Store tokens
            localStorage.setItem('access_token', tokens.access_token);
            if (tokens.refresh_token) {
              localStorage.setItem('refresh_token', tokens.refresh_token);
            }
            // Clean up
            sessionStorage.removeItem('code_verifier');
            sessionStorage.removeItem('state');
          });
      }
    }
  }, [client]);

  return (
    <div>
      <button onClick={handleLogin}>Login with Google</button>
    </div>
  );
}
```

---

## Configuration

Before running the examples, make sure to:

1. **Start your API Forge backend**:
   ```bash
   uv run api-forge-cli deploy up dev
   uvicorn main:app --reload
   ```

2. **Configure your OIDC provider** (e.g., Google):
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create OAuth 2.0 credentials
   - Add redirect URI: `http://localhost:8080/callback` (Python) or `http://localhost:3000/callback` (TypeScript)
   - Copy Client ID and Client Secret

3. **Update your API Forge `.env` file**:
   ```env
   OIDC_GOOGLE_CLIENT_ID=your-client-id
   OIDC_GOOGLE_CLIENT_SECRET=your-client-secret
   ```

4. **Update the example code**:
   - Replace `your-client-id` with your actual client ID
   - Update `api_base_url` if your API is hosted elsewhere
   - Adjust the redirect URI to match your setup

## Testing with Keycloak (Development)

If you're using the development environment with Keycloak:

```python
# Python
client = APIForgeClient(
    api_base_url="http://localhost:8000",
    client_id="test-client",
    redirect_uri="http://localhost:8080/callback",
    provider="keycloak"
)
```

```typescript
// TypeScript
const client = new APIForgeClient(
  'http://localhost:8000',
  'test-client',
  'http://localhost:3000/callback',
  'keycloak'
);
```

Default Keycloak test users:
- Username: `testuser1` / Password: `password123`
- Username: `testuser2` / Password: `password123`

## Security Best Practices

1. **Never expose client secrets** - Use PKCE flow (these examples do this correctly)
2. **Store tokens securely**:
   - Browser: Use HttpOnly cookies or secure localStorage
   - Mobile: Use secure keychain/keystore
   - Server: Use encrypted storage
3. **Validate state parameter** - Prevents CSRF attacks
4. **Use HTTPS in production** - Never send tokens over HTTP
5. **Implement token refresh** - Handle expired tokens gracefully
6. **Clear tokens on logout** - Remove all stored credentials

## Troubleshooting

### "Invalid redirect URI"
- Ensure the redirect URI in your code matches the one registered with your OIDC provider
- Check for trailing slashes and protocol (http vs https)

### "PKCE verification failed"
- Make sure you're using the same `code_verifier` that generated the `code_challenge`
- Don't URL-encode the verifier

### "Token expired"
- Implement token refresh logic
- Check your system clock is synchronized

### "CORS errors" (Browser)
- Configure CORS in your API Forge `config.yaml`:
  ```yaml
  app:
    cors:
      enabled: true
      allowed_origins:
        - "http://localhost:3000"
      allow_credentials: true
  ```

## Related Documentation

- [OIDC Authentication & BFF Pattern](../docs/fastapi-auth-oidc-bff.md)
- [Sessions and Cookies](../docs/fastapi-sessions-and-cookies.md)
- [Python OIDC Client Guide](../docs/examples-python-oidc-client.md)
- [JavaScript OIDC Client Guide](../docs/examples-javascript-oidc-client.md)

## License

MIT License - Same as API Forge
