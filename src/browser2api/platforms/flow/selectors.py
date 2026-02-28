"""Constants and selectors for Google Flow (labs.google/fx/tools/flow)."""

DOMAIN = "https://labs.google"
TOOL_URL = f"{DOMAIN}/fx/tools/flow"

# Login state detection
PROFILE_AVATAR_SELECTOR = 'img[aria-label*="Google Account"]'
PROFILE_IMG_SELECTOR = 'img[src*="googleusercontent.com/a/"]'
SIGN_IN_LINK_SELECTOR = 'a[href*="accounts.google.com"]'

# Prompt input — Flow may use textarea, contenteditable div, or input
PROMPT_TEXTAREA_SELECTOR = 'textarea'
PROMPT_CONTENTEDITABLE_SELECTOR = '[contenteditable="true"]'
PROMPT_INPUT_SELECTOR = 'input[type="text"]'

# Generate button
GENERATE_BUTTON_SELECTOR = 'button[aria-label="Generate"]'

# Image containers
IMAGE_CONTAINER_SELECTOR = 'img[src*="googleusercontent.com"]'

# CDN URL patterns for image detection
CDN_PATTERNS = [
    "googleusercontent.com",
    "lh3.google",
    "gstatic.com",
]
