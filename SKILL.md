# dontmissddl — Claude Code Skill

Trigger: user mentions deploying, debugging, or configuring their dontmissddl instance.

## What this skill helps with

- Walk through first-time setup (Feishu app creation, GitHub Secrets, fork)
- Debug extraction issues (too many false positives / missing DDLs)
- Tune the DDL extraction prompt
- Check current DDL list from data/ddls.json
- Add new Feishu groups to monitor

## Setup flow

1. Guide user to create a Feishu app at open.feishu.cn
   - Enable Bot capability
   - Add permission: `im:message`
   - Publish the app (admin approval may be needed)
2. Add bot to target groups, get `chat_id` for each
3. Fork this repo
4. Set GitHub Secrets: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_GROUP_IDS, LLM_API_KEY
5. Enable GitHub Actions in the forked repo
6. Done — it runs every 10 minutes

## How it works (explain to user)

No server needed. GitHub Actions runs `python -m server.main all` every 10 min:
- `poll` step: calls Feishu API to list recent messages → LLM extracts DDLs → saves to data/ddls.json
- `remind` step: checks ddls.json for upcoming deadlines → sends Feishu Bot messages
- Changed data files are committed back to the repo automatically

## Debugging

- Check Actions logs: GitHub repo → Actions tab
- Read current DDLs: open `data/ddls.json`
- Check extraction prompt: `prompts/extract-ddl.md`
- Test extraction locally:
  ```
  pip install -r requirements.txt
  cp .env.example .env  # fill in values
  python -m server.main poll
  ```

## Prompt tuning

The extraction prompt is at `prompts/extract-ddl.md`. Common fixes:
- Too many false positives → add negative examples to the prompt
- Missing DDLs → relax time expression rules
- Wrong dates → check the {current_date} template variable
