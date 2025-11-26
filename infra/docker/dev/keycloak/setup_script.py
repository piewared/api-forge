#!/usr/bin/env python3
"""Docker container setup script that calls the main Keycloak setup."""

import os
import sys
import time

from src.dev.setup_keycloak import KeycloakSetup

# Add the src directory to the Python path
sys.path.insert(0, "/app/src")

try:
    # Use the container's internal hostname for Keycloak
    keycloak_url = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")

    print(f"🔧 Configuring Keycloak at {keycloak_url}...")

    # Wait a bit more for Keycloak to be fully ready
    time.sleep(10)

    setup = KeycloakSetup(base_url=keycloak_url)
    setup.setup_all()

    print("\n✅ Keycloak configuration complete!")
    print("🎉 Keycloak is ready for development with test realm and users!")

except Exception as e:
    print(f"❌ Setup error: {e}")
    print("Keycloak may still be starting up. You can run setup manually later.")
    # Don't exit with error code to avoid container restart loops
    sys.exit(0)
