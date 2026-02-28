"""Constants and selectors for 即梦AI (Jimeng)."""

DOMAIN = "https://jimeng.jianying.com"
HOME_URL = f"{DOMAIN}/ai-tool/home"
LOGIN_URL = f"{DOMAIN}/ai-tool/image/generate"

# CSS selectors for login state detection
LOGGED_IN_SELECTOR = "xpath=//div[contains(@class, 'avatar')]"
LOGIN_BUTTON_SELECTOR = "xpath=//button[contains(text(), '登录')]"
