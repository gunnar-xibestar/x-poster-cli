# Getting keys

After installing, get your keys, then put them in the env file (see [Configuration](CONFIGURATION.md)).

**X API (required)**: official docs: <https://docs.x.com/fundamentals/developer-apps>
1. Sign in to the X Developer Console at <https://console.x.com> and finish the developer onboarding.
2. Create an App (under **Apps**).
3. In the App's **User authentication settings**, set **App permissions** to **Read and write**
   (xbot posts replies and mutes through your account with OAuth 1.0a).
4. In the App's **Keys and tokens**, copy these into the env file ([env file setup](CONFIGURATION.md)). Each secret is shown only once:
   | env variable | where it comes from |
   |---|---|
   | `X_API_KEY` | API Key (consumer key) |
   | `X_API_SECRET` | API Key Secret (consumer secret) |
   | `X_ACCESS_TOKEN` | Access Token (generate it for your own account) |
   | `X_ACCESS_TOKEN_SECRET` | Access Token Secret |
   If you change the permissions later, regenerate the Access Token and Secret.
5. X API usage is paid per request (pay-per-use credits). Check your plan and credits in the console.

**xAI (optional, for Grok drafts)**: official docs: <https://docs.x.ai/developers/quickstart>
1. Sign up at <https://console.x.ai>.
2. Buy prepaid credits (**Billing → API spend management**); a team without credits can't use the API.
3. Create a key on the **API Keys** page and put it in `XAI_API_KEY` (not `OPENAI_API_KEY`).
   Keep `XBOT_BASE_URL=https://api.x.ai/v1`. You can leave both empty to run X-only.

## xAI management key (optional: real credit balance)
Without it the status bar shows an estimate (`xbot config credits_start`); with it, your real prepaid balance.
1. In <https://console.x.ai> open your team's settings → **Management Keys** (your console user needs permission to manage them) and create a key.
2. Give it **Billing: Read only** access (nothing else is needed; without billing access xbot shows `balance unavailable (management key lacks billing access) · showing estimate`).
3. Run `xbot secrets` and paste it into the `XAI_MANAGEMENT_KEY=` line (top of `~/.config/xbot/env`).
4. xbot finds your team through `XAI_API_KEY` (or set `XAI_TEAM_ID=` yourself) and reads the balance at startup and every 5 minutes: `credits: $X.XX (xAI, as of HH:MM)`. The key is treated as a secret: redacted, never logged or printed.
