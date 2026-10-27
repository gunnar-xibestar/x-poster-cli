# Grok drafting: `/align` and learning from your edits

Two things shape how Grok writes your reply drafts: the **persona** you set with `/align`, and **style examples** learned from drafts you edit.

## `/align <persona text>`
Sets Grok's persona and instructions for every future draft, for example:

```
/align dry wit, practical Linux tips, no hype
```

- It replaces the previous persona; it doesn't add to it.
- It's saved to `config.json` right away and applies to every draft Grok writes from then on.

## Learning from your last 8 edits
When you edit a Grok draft (`e` in the queue, or the reply editor) and then approve or save it, xbot remembers three things: the original post, Grok's draft, and your final text.

- They're stored in `~/.local/state/xbot/style_examples.jsonl`. Only the newest 50 are kept, and long text is clipped.
- A draft you didn't change isn't stored.
- Each time Grok drafts a reply, the **newest 8** are added to the prompt as "replies in the user's voice", so Grok picks up your tone, length and wording.
- Posts you hid, filtered or blocked are never used as examples.
- `/align` says *what* to sound like; the edit examples *show* it. Both are sent together.

## Settings and commands
| What | How |
|---|---|
| Change how many edits are used | `xbot config style_examples 8` (any number; default 8) |
| Turn edit learning off | `xbot config style_examples 0` |
| See how many are stored | `/style` |
| Forget all stored edits | `/style clear` |

In `xbot sample` none of this touches your real profile: the persona, edits and examples live in a temporary folder that is deleted on exit.
