# Discord Message Repeater Bot (User-Side App)

A Discord bot built with `discord.py 2.x` supporting **User-Side App installation** (use it anywhere across Discord) and strictly gated by the **Discord Server Tag / Clan Identity** of server `1360158665230782614`.

---

## 🏷 Server Tag Verification
Only users who are actively **wearing the Server Tag / Clan Badge** of server:
`1360158665230782614`
will be permitted to execute commands or interact with the quick-action buttons.
- The bot checks memory profile data and performs a live Discord REST API verification.
- Non-tagged users will immediately receive an ephemeral **Access Denied** message.

---

## 📱 User App (Use Everywhere)
Because this bot is configured as a **User App**, you do **NOT** need the bot to be invited to a server to use it! You can install it directly to your personal Discord account and use `/spamraid` and `/embedspam` in:
- Any Discord server
- Direct Messages (DMs)
- Group chats

### How to Install to your Discord Account:
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Select your application.
3. In the left menu, click **Installation**:
   - Under **Installation Contexts**, ensure **User Install** and **Guild Install** are checked.
   - Under **Default Install Settings**, ensure scopes have `applications.commands` and `bot`.
   - Save changes.
4. Click this link to install the app to your personal account:
   **[👉 Install App to your Discord Account](https://discord.com/oauth2/authorize?client_id=1560685724498395246)**
5. Choose **"Install to My Account"**.

---

## 💬 Slash Commands

### 1. `/spamraid` (Standard Message with Quick Buttons)
Send a message with interactive buttons as shown in the demo.
- `message`: Text message to send (e.g. `"# Hello everyone https://discord.gg/..."`)
- `delay`: *(Optional)* Seconds between messages (default: `0s` for maximum burst speed)
- `amount`: *(Optional)* Direct count if you don't want to use the buttons

#### 🕹️ Quick-Action Buttons:
Executing `/spamraid` displays an ephemeral control panel with:
- 🔴 **`Spam x1`** — Sends 1 message
- 🟢 **`Spam x10`** — Sends 10 messages
- 🔵 **`Spam x16`** — Sends 16 messages

---

### 2. `/embedspam` (Rich Embeds with Quick Buttons)
Repeat rich, formatted Discord embeds.
- `title`: Embed title
- `description`: Main content of the embed
- `color`: *(Optional)* Choose from preset colors (🔴 Red, 🔵 Blue, 🟢 Green, 🟣 Purple, 🟡 Gold, 🌸 Pink, ⚫ Dark, or 🎲 Random which picks a new color on every message!) or provide a hex code (`#FF0000`).
- `delay`: *(Optional)* Delay between sends (default: `0s`)
- `amount`: *(Optional)* Direct amount, or use the interactive buttons
- `footer`: *(Optional)* Text at the bottom of the embed
- `image_url`: *(Optional)* Large image URL
- `thumbnail_url`: *(Optional)* Small thumbnail image URL

---

### 3. `/say` (Speak as Bot without Reply Link)
Makes the bot speak directly in the channel without showing `<User> used /say` or replying to your command.
- `message`: The message for the bot to post
```
/say message:Hello everyone!
```

---

### 4. `/stop` (Cancel Task)
Immediately aborts all active repeating tasks currently running in that chat session.
```
/stop
```

---

## 🚀 Running the Bot

Double click [`run.bat`](file:///f:/Games/netc2/discord_bot/run.bat) or run from terminal:
```bash
cd f:\Games\netc2\discord_bot
python bot.py
```
