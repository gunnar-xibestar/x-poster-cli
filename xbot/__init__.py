"""xbot: a Textual TUI X (Twitter) client with optional Grok-drafted replies.

Package map (what's where):
  app.py       Textual UI: feed, draft queue, console, cards, popups, key bindings
  bot.py       Poll loop: search/mentions, draft via LLM, queue, approve/send
  video.py     In-terminal mpv media viewer (v / [media] click)
  xapi.py      X API v2 (live + DryRunX for sample/offline)
  llm.py       Grok via the OpenAI-compatible xAI chat API
  queue.py     Pending reply drafts awaiting your approve/reject/edit
  sample.py    `xbot sample`: real TUI with fake data, temp state, no network
  config.py    Paths, Config dataclass, env loading (never logs secrets)
  state.py     Seen posts, likes, hides, spend log (state.json)
  style.py     Few-shot examples learned from your edited Grok drafts
  credits.py   Combined X+Grok spend, /limit, management-key balance
  safety.py    Local adult/spam filter (free; no API)
  tags.py      Keyword/hashtag tagger + search exclusion builder
  render.py    Rich markup for the feed and status line
  commands.py  Slash-command parsing
  help.py      /help text
  opener.py    Open URLs in the browser (WSL2-aware)
  oauth2.py    `xbot login` OAuth 2.0 for likes
  oembed.py    Free author lookup (no API credits)
  envedit.py   `xbot secrets` (edit env in nano; never prints values)
  configcli.py `xbot config` shell CLI
  secure.py    Private file modes, redaction, minimal subprocess env
  log.py       actions.jsonl event log
  textutil.py  Display clipping / emoji-width cleanup
"""
