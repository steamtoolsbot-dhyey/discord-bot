import os
import re
import random
import asyncio
import logging
from datetime import datetime
from collections import defaultdict
from typing import Dict, Optional, Set, Tuple
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("DiscordRepeater")

# Server (Guild) ID for strict tag locking
ALLOWED_GUILD_ID = int(os.getenv("ALLOWED_GUILD_ID", "1360158665230782614"))
ALLOWED_TAG_NAME = os.getenv("ALLOWED_TAG_NAME", "XERO").strip().upper()

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Track active repeater tasks per channel or user session to allow stacking and /stop
active_tasks: Dict[int, Set[asyncio.Task]] = defaultdict(set)

# Short TTL cache to make tag checks instantaneous while avoiding Discord REST rate limits
user_tag_cache: Dict[int, Tuple[bool, float, str]] = {}
CACHE_TTL = 120.0  # seconds — long TTL to avoid REST round-trips on Railway

MAX_MESSAGE_COUNT = 1000
MIN_DELAY_SECONDS = 0.0
DEFAULT_DELAY = 0.0

# Pre-made messages for the dropdown menu
PRE_MADE_MESSAGES = [
    ("XERO NATION RAID", "# THIS SERVER IS RAIDED BY XERO NATION\n\nhttps://discord.gg/nationxero"),
]


class RepeaterBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=[], intents=intents, help_command=None)

    async def setup_hook(self):
        logger.info(f"🔒 STRICT LOCK ENABLED: Users MUST wear the server tag of Guild ID {ALLOWED_GUILD_ID} ('{ALLOWED_TAG_NAME}')")
        logger.info("   All users without the active server tag will be blocked.")

        # Sync commands globally for User App and Guild App
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Successfully synced {len(synced)} command(s) globally (User & Guild Apps enabled)!")
            for cmd in synced:
                logger.info(f"   - /{cmd.name}")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        # Non-admin permissions: View Channels, Send Messages, Embed Links, Attach Files, Read History, Send in Threads
        guild_invite = f"https://discord.com/oauth2/authorize?client_id={self.user.id}&permissions=274878286848&scope=bot%20applications.commands"
        user_invite = f"https://discord.com/oauth2/authorize?client_id={self.user.id}&scope=applications.commands"
        logger.info("======================================================================")
        logger.info(f"BOT SERVER INVITE (Non-Admin, View/Send Messages, Embeds & History):")
        logger.info(f"  👉 {guild_invite}")
        logger.info(f"USER APP INSTALL LINK (User integration only, cannot be pinged):")
        logger.info(f"  👉 {user_invite}")
        logger.info("======================================================================")

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if self.user and self.user.mentioned_in(message) and not message.mention_everyone:
            embed = discord.Embed(
                title=f"🤖 {self.user.name} is Online!",
                description=(
                    "I am active in this server! Use my slash commands:\n\n"
                    "• `/spamraid` — Repeat text with quick action buttons\n"
                    "• `/embedspam` — Send customizable rich embeds\n"
                    "• `/say` — Speak as bot without reply link\n"
                    "• `/stop` — Abort repeating tasks in channel"
                ),
                color=0x6F8CFF,
            )
            embed.set_footer(text=f"Server Tag: '{ALLOWED_TAG_NAME}' (Guild ID: {ALLOWED_GUILD_ID})")
            try:
                await message.reply(embed=embed, mention_author=False)
            except Exception:
                pass
        await self.process_commands(message)


bot = RepeaterBot()


def can_use_channel_send(interaction: discord.Interaction) -> bool:
    """
    CRITICAL CHECK:
    - Returns True ONLY if:
      1) The bot is an invited member of the guild (bot.get_guild(...) is not None).
      2) OR it is an actual DMChannel directly with the bot.
    - If running as an uninvited User App in a server channel, returns False!
      This prevents calling channel.send() which triggers 403 Forbidden (Missing Access) and 429 rate limit locks.
    """
    if interaction.guild_id is not None:
        return bot.get_guild(interaction.guild_id) is not None

    # If guild_id is None, it could be an ephemeral interaction from a server channel or a real DM
    if interaction.channel_id:
        cached_channel = bot.get_channel(interaction.channel_id)
        if cached_channel is not None:
            if isinstance(cached_channel, discord.DMChannel):
                return True
            if getattr(cached_channel, "guild", None) is not None:
                return bot.get_guild(cached_channel.guild.id) is not None

    if isinstance(interaction.channel, discord.DMChannel):
        return True
    if getattr(interaction.channel, "type", None) == discord.ChannelType.private:
        return True

    return False


async def check_user_server_tag(user: discord.User | discord.Member) -> Tuple[bool, str]:
    """
    STRICT CHECK: Verifies that the user is actively wearing the Server Tag / Clan Badge
    of server 1360158665230782614.
    """
    now = asyncio.get_event_loop().time()
    if user.id in user_tag_cache:
        has_access, expire_at, reason = user_tag_cache[user.id]
        if now < expire_at:
            return has_access, reason

    # 1. Check PrimaryGuild object on User or Member
    pg = getattr(user, "primary_guild", None)
    if pg is not None:
        pg_id = getattr(pg, "id", None)
        pg_tag = getattr(pg, "tag", None)

        if pg_id and int(pg_id) == ALLOWED_GUILD_ID:
            user_tag_cache[user.id] = (True, now + CACHE_TTL, f"PrimaryGuild ID: {pg_id} (tag: {pg_tag})")
            return True, f"PrimaryGuild ID: {pg_id} (tag: {pg_tag})"

    # 2. Check internal raw payload on user._user or user
    raw_user = getattr(user, "_user", user)
    raw_pg = getattr(raw_user, "_primary_guild", None)
    if isinstance(raw_pg, dict):
        gid = raw_pg.get("identity_guild_id")
        tag = raw_pg.get("tag")
        if gid and int(gid) == ALLOWED_GUILD_ID:
            user_tag_cache[user.id] = (True, now + CACHE_TTL, f"Raw identity_guild_id: {gid} (tag: {tag})")
            return True, f"Raw identity_guild_id: {gid}"

    # 3. Direct REST API Fetch via bot.http.get_user
    try:
        full_data = await bot.http.get_user(user.id)
        if isinstance(full_data, dict):
            # Check 'primary_guild'
            pg_dict = full_data.get("primary_guild")
            if isinstance(pg_dict, dict):
                gid = pg_dict.get("identity_guild_id")
                tag = pg_dict.get("tag")
                if gid and int(gid) == ALLOWED_GUILD_ID:
                    user_tag_cache[user.id] = (True, now + CACHE_TTL, f"REST PrimaryGuild: {gid} (tag: {tag})")
                    return True, f"REST PrimaryGuild: {gid}"

            # Check 'clan'
            clan_dict = full_data.get("clan")
            if isinstance(clan_dict, dict):
                gid = clan_dict.get("identity_guild_id")
                tag = clan_dict.get("tag")
                if gid and int(gid) == ALLOWED_GUILD_ID:
                    user_tag_cache[user.id] = (True, now + CACHE_TTL, f"REST Clan: {gid} (tag: {tag})")
                    return True, f"REST Clan: {gid}"
    except Exception as e:
        logger.warning(f"Error fetching full user profile from REST API for {user.id}: {e}")

    user_tag_cache[user.id] = (False, now + 10.0, f"No server tag found for Guild ID {ALLOWED_GUILD_ID}")
    return False, f"Server tag of Guild {ALLOWED_GUILD_ID} not detected on profile"


async def enforce_server_tag(interaction: discord.Interaction) -> bool:
    """Helper to check access, log to console, and send access denied message if unauthorized."""
    has_access, reason = await check_user_server_tag(interaction.user)
    status_str = "ALLOWED" if has_access else "BLOCKED"
    logger.info(f"[TAG CHECK] User: {interaction.user} (ID: {interaction.user.id}) -> {status_str} ({reason})")

    if not has_access:
        await interaction.response.send_message(
            f"⛔ **Access Denied: Server Tag Required**\n\n"
            f"This bot is strictly locked to users wearing the **Server Tag** of server `{ALLOWED_GUILD_ID}`.\n"
            f"You must set this server as your primary guild / clan badge on your Discord profile to use this command.\n\n"
            f"*(Current profile status: {reason})*",
            ephemeral=True
        )
        return False

    return True


bot.tree.interaction_check = enforce_server_tag


def parse_color(color_name: Optional[str]) -> int:
    """Helper to convert color names or hex strings into a Discord integer color."""
    if not color_name:
        return 0x3498DB  # Default Blue

    color_lower = color_name.lower().strip()
    color_map = {
        "red": 0xFF3333,
        "green": 0x33FF57,
        "blue": 0x3380FF,
        "purple": 0x9B59B6,
        "gold": 0xF1C40F,
        "orange": 0xE67E22,
        "pink": 0xFF69B4,
        "dark": 0x2B2D31,
        "white": 0xFFFFFF
    }

    if color_lower in color_map:
        return color_map[color_lower]

    cleaned_hex = color_lower.lstrip("#")
    try:
        return int(cleaned_hex, 16)
    except ValueError:
        return 0x3498DB


def make_spamraid_embed(message: str, delay_str: str) -> discord.Embed:
    """Creates the exact embed UI shown in the reference screenshot."""
    embed = discord.Embed(
        title="SpamRaid",
        color=0x3498DB
    )
    # Field 1: Message in codeblock box
    embed.add_field(
        name="Message",
        value=f"```\n{message}\n```",
        inline=False
    )
    # Field 2: Delay
    embed.add_field(
        name="Delay: " + delay_str,
        value="",
        inline=False
    )
    # Footer: XERO NATION | Today at H:MM AM/PM
    now_str = datetime.now().strftime("%I:%M %p").lstrip("0")
    tag_name = ALLOWED_TAG_NAME if ALLOWED_TAG_NAME else "XERO NATION"
    embed.set_footer(text=f"{tag_name} | Today at {now_str}")
    return embed


async def run_repeater(
    interaction: discord.Interaction,
    session_key: int,
    amount: int,
    delay: float,
    content: Optional[str] = None,
    embed_data: Optional[dict] = None
):
    """
    High-speed concurrent message sender.
    Sends in parallel bursts for maximum throughput, only sleeping between bursts when delay > 0.
    Falls back from channel.send to interaction.followup automatically on permission errors.
    """
    channel = interaction.channel
    use_channel = can_use_channel_send(interaction) and channel is not None and hasattr(channel, "send")

    sent_count = 0
    # Discord allows ~5 messages per channel per 5s bucket. Burst that many concurrently.
    BURST_SIZE = 5

    def build_embed():
        if embed_data is None:
            return None
        col = random.randint(0, 0xFFFFFF) if embed_data.get("is_random_color") else embed_data["color"]
        emb = discord.Embed(
            title=embed_data.get("title"),
            description=embed_data.get("description"),
            color=col
        )
        if embed_data.get("footer"):
            emb.set_footer(text=embed_data["footer"])
        if embed_data.get("image_url"):
            emb.set_image(url=embed_data["image_url"])
        if embed_data.get("thumbnail_url"):
            emb.set_thumbnail(url=embed_data["thumbnail_url"])
        return emb

    async def send_one():
        """Send a single message with retry logic. Returns True on success."""
        nonlocal use_channel
        max_retries = 3
        for attempt in range(max_retries):
            try:
                emb = build_embed()
                if use_channel:
                    try:
                        await channel.send(content=content, embed=emb)
                        return True
                    except (discord.Forbidden, discord.HTTPException) as chan_err:
                        is_missing_access = (
                            isinstance(chan_err, discord.Forbidden)
                            or getattr(chan_err, "status", None) == 403
                            or getattr(chan_err, "code", None) == 50001
                        )
                        if is_missing_access:
                            logger.info("channel.send lacking server access (50001). Switching to interaction.followup.")
                            use_channel = False
                            await interaction.followup.send(content=content, embed=emb, ephemeral=False)
                            return True
                        raise
                else:
                    await interaction.followup.send(content=content, embed=emb, ephemeral=False)
                    return True

            except discord.RateLimited as rl:
                wait_time = float(rl.retry_after or 0.5)
                logger.warning(f"Rate limited (bucket). Sleeping {wait_time:.2f}s...")
                await asyncio.sleep(wait_time)

            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = float(getattr(e, "retry_after", 0.5) or 0.5)
                    logger.warning(f"429 rate limit. Sleeping {retry_after:.2f}s...")
                    await asyncio.sleep(retry_after)
                elif "followup" in e.text.lower() or e.code == 50058 or (e.status in (400, 403) and "maximum" in e.text.lower()):
                    logger.warning(f"Followup token limit reached.")
                    return False
                else:
                    if attempt == max_retries - 1:
                        logger.error(f"Failed to send message: {e}")
                        return False
                    await asyncio.sleep(0.1)
        return False

    try:
        remaining = amount
        while remaining > 0:
            if delay > 0:
                # Respect user-set delay: send one at a time with the delay between each
                ok = await send_one()
                if ok:
                    sent_count += 1
                else:
                    break
                remaining -= 1
                if remaining > 0:
                    await asyncio.sleep(delay)
            else:
                # Zero delay: fire concurrent bursts for maximum speed
                burst = min(BURST_SIZE, remaining)
                results = await asyncio.gather(*(send_one() for _ in range(burst)), return_exceptions=True)
                for r in results:
                    if r is True:
                        sent_count += 1
                    elif isinstance(r, asyncio.CancelledError):
                        raise r
                remaining -= burst

        logger.info(f"✅ Successfully finished sending {sent_count}/{amount} items for session {session_key}.")
    except asyncio.CancelledError:
        logger.info(f"Repeater cancelled after sending {sent_count}/{amount} items for session {session_key}.")
        raise


def get_environment_info(interaction: discord.Interaction) -> Tuple[bool, str]:
    """Determines whether the bot is invited in the server or running as a limited User App."""
    if can_use_channel_send(interaction):
        return True, "Server Member (Unlimited)"
    return False, "User App"


# ==========================================
# PRE-MADE MESSAGE SELECT MENU (Dropdown)
# ==========================================
class PreMadeMessageSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=val)
            for label, val in PRE_MADE_MESSAGES
        ]
        super().__init__(
            placeholder="Select a pre-made message",
            min_values=1,
            max_values=1,
            options=options,
            row=1
        )

    async def callback(self, select_interaction: discord.Interaction):
        view: SpamRaidControlView = self.view
        selected_msg = self.values[0]
        view.content = selected_msg

        delay_str = f"{view.delay:g}s" if view.delay > 0 else "0s"
        new_embed = make_spamraid_embed(selected_msg, delay_str)
        await select_interaction.response.edit_message(embed=new_embed, view=view)


# ==========================================
# INTERACTIVE BUTTON VIEW (As shown in screenshot)
# ==========================================
class SpamRaidControlView(discord.ui.View):
    def __init__(
        self,
        author_id: int,
        content: Optional[str] = None,
        embed_data: Optional[dict] = None,
        delay: float = 0.0,
        timeout: Optional[float] = 600.0,
        is_embed_mode: bool = False
    ):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.content = content
        self.embed_data = embed_data
        self.delay = delay
        self.is_embed_mode = is_embed_mode

        # Add the dropdown menu on row 1 for standard text spam
        if not is_embed_mode:
            self.add_item(PreMadeMessageSelect())

    async def interaction_check(self, button_interaction: discord.Interaction) -> bool:
        # Only check ownership here — tag check already handled by global tree.interaction_check
        if button_interaction.user.id != self.author_id:
            await button_interaction.response.send_message(
                "❌ Only the user who executed this command can use these buttons.",
                ephemeral=True
            )
            return False
        return True

    async def trigger_spam(self, button_interaction: discord.Interaction, amount: int):
        try:
            await button_interaction.response.edit_message(view=self)
        except Exception:
            try:
                await button_interaction.response.defer()
            except Exception:
                pass

        session_key = button_interaction.channel_id or button_interaction.user.id

        task = asyncio.create_task(
            run_repeater(
                interaction=button_interaction,
                session_key=session_key,
                amount=amount,
                delay=self.delay,
                content=self.content,
                embed_data=self.embed_data
            )
        )
        active_tasks[session_key].add(task)
        task.add_done_callback(lambda t: active_tasks[session_key].discard(t))

    @discord.ui.button(label="Spam x1", style=discord.ButtonStyle.danger, row=0)
    async def btn_spam_1(self, button_interaction: discord.Interaction, button: discord.ui.Button):
        await self.trigger_spam(button_interaction, 1)

    @discord.ui.button(label="Spam x10", style=discord.ButtonStyle.success, row=0)
    async def btn_spam_10(self, button_interaction: discord.Interaction, button: discord.ui.Button):
        await self.trigger_spam(button_interaction, 10)

    @discord.ui.button(label="Spam x16", style=discord.ButtonStyle.primary, row=0)
    async def btn_spam_16(self, button_interaction: discord.Interaction, button: discord.ui.Button):
        await self.trigger_spam(button_interaction, 16)


# ==========================================
# SLASH COMMAND: /spamraid
# ==========================================
@bot.tree.command(name="spamraid", description="Repeat a message multiple times with quick-action buttons.")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(
    message="Message to spam",
    delay="Seconds between messages (default 0s, set higher if needed)",
    amount="Optional custom amount (leave blank to use Spam x1, x10, x16 buttons)"
)
async def slash_spamraid(
    interaction: discord.Interaction,
    message: str,
    delay: Optional[float] = 0.0,
    amount: Optional[int] = None
):
    delay = max(MIN_DELAY_SECONDS, float(delay if delay is not None else 0.0))
    delay_str = f"{delay:g}s" if delay > 0 else "0s"

    # If amount is explicitly specified, start sending directly
    if amount is not None and amount > 0:
        session_key = interaction.channel_id or interaction.user.id

        if amount > MAX_MESSAGE_COUNT:
            await interaction.response.send_message(
                f"❌ Maximum allowed is {MAX_MESSAGE_COUNT} messages.",
                ephemeral=True
            )
            return

        has_unlimited, info = get_environment_info(interaction)
        notice = ""
        if not has_unlimited and amount > 5:
            notice = (
                f"\n\n⚠️ **Notice:** This server does not have the bot invited. "
                f"Discord limits uninvited User Apps to **5 messages** max per command. "
                f"[Invite Bot to Server](https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=84992&scope=bot%20applications.commands) to send {amount} messages."
            )

        await interaction.response.send_message(
            f"🚀 Started sending **{amount}** messages (delay: `{delay_str}`). Use `/stop` to abort.{notice}",
            ephemeral=True
        )

        task = asyncio.create_task(
            run_repeater(
                interaction=interaction,
                session_key=session_key,
                amount=amount,
                delay=delay,
                content=message
            )
        )
        active_tasks[session_key].add(task)
        task.add_done_callback(lambda t: active_tasks[session_key].discard(t))
        return

    # Ephemeral Control Panel with exact UI from reference screenshot
    embed = make_spamraid_embed(message, delay_str)
    view = SpamRaidControlView(
        author_id=interaction.user.id,
        content=message,
        delay=delay
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ==========================================
# SLASH COMMAND: /embedspam
# ==========================================
@bot.tree.command(name="embedspam", description="Repeat rich embeds with quick-action buttons.")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(
    title="Embed title",
    description="Embed description / main content",
    color="Color (Red, Blue, Green, Purple, Gold, Pink, Random, or Hex code like #FF0000)",
    delay="Seconds between sends (default 0s)",
    amount="Optional custom amount (leave blank to use Spam x1, x10, x16 buttons)",
    footer="Optional footer text",
    image_url="Optional large image URL",
    thumbnail_url="Optional small thumbnail image URL"
)
@app_commands.choices(color=[
    app_commands.Choice(name="🔴 Red", value="red"),
    app_commands.Choice(name="🔵 Blue", value="blue"),
    app_commands.Choice(name="🟢 Green", value="green"),
    app_commands.Choice(name="🟣 Purple", value="purple"),
    app_commands.Choice(name="🟡 Gold", value="gold"),
    app_commands.Choice(name="🌸 Pink", value="pink"),
    app_commands.Choice(name="⚫ Dark", value="dark"),
    app_commands.Choice(name="🎲 Random (Changes every message)", value="random"),
])
async def slash_embedspam(
    interaction: discord.Interaction,
    title: str,
    description: str,
    color: Optional[app_commands.Choice[str]] = None,
    delay: Optional[float] = 0.0,
    amount: Optional[int] = None,
    footer: Optional[str] = None,
    image_url: Optional[str] = None,
    thumbnail_url: Optional[str] = None
):
    delay = max(MIN_DELAY_SECONDS, float(delay if delay is not None else 0.0))
    delay_str = f"{delay:g}s" if delay > 0 else "0s"

    selected_color_val = color.value if color else "blue"
    is_random = (selected_color_val == "random")
    parsed_col = parse_color(selected_color_val)

    embed_data = {
        "title": title,
        "description": description,
        "color": parsed_col,
        "is_random_color": is_random,
        "footer": footer,
        "image_url": image_url,
        "thumbnail_url": thumbnail_url
    }

    if amount is not None and amount > 0:
        session_key = interaction.channel_id or interaction.user.id

        if amount > MAX_MESSAGE_COUNT:
            await interaction.response.send_message(
                f"❌ Maximum allowed amount is {MAX_MESSAGE_COUNT}.",
                ephemeral=True
            )
            return

        has_unlimited, info = get_environment_info(interaction)
        notice = ""
        if not has_unlimited and amount > 5:
            notice = (
                f"\n\n⚠️ **Notice:** This server does not have the bot invited. "
                f"Discord limits uninvited User Apps to **5 messages** max per command. "
                f"[Invite Bot to Server](https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=84992&scope=bot%20applications.commands) to send {amount} messages."
            )

        await interaction.response.send_message(
            f"🚀 Started sending **{amount}** embeds (delay: `{delay_str}`). Use `/stop` to cancel at any time.{notice}",
            ephemeral=True
        )

        task = asyncio.create_task(
            run_repeater(
                interaction=interaction,
                session_key=session_key,
                amount=amount,
                delay=delay,
                content=None,
                embed_data=embed_data
            )
        )
        active_tasks[session_key].add(task)
        task.add_done_callback(lambda t: active_tasks[session_key].discard(t))
        return

    panel_embed = discord.Embed(
        title=f"SpamRaid: {title}",
        description=f"```\n{description}\n```\n**Delay:** {delay_str}",
        color=parsed_col
    )
    if footer:
        panel_embed.set_footer(text=footer)
    else:
        now_str = datetime.now().strftime("%I:%M %p").lstrip("0")
        tag_name = ALLOWED_TAG_NAME if ALLOWED_TAG_NAME else "XERO NATION"
        panel_embed.set_footer(text=f"{tag_name} | Today at {now_str}")
    if thumbnail_url:
        panel_embed.set_thumbnail(url=thumbnail_url)
    if image_url:
        panel_embed.set_image(url=image_url)

    view = SpamRaidControlView(
        author_id=interaction.user.id,
        embed_data=embed_data,
        delay=delay,
        is_embed_mode=True
    )
    await interaction.response.send_message(embed=panel_embed, view=view, ephemeral=True)


# ==========================================
# SLASH COMMAND: /say
# ==========================================
@bot.tree.command(name="say", description="Make the bot say something in the chat without replying to your command.")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(
    message="The text message you want the bot to say"
)
async def slash_say(
    interaction: discord.Interaction,
    message: str
):
    # Ephemeral immediate response
    await interaction.response.send_message("💬 Sending...", ephemeral=True)

    channel = interaction.channel

    # If bot is a member of the guild or in DM, send via channel.send (zero reply header)
    if can_use_channel_send(interaction) and channel is not None and hasattr(channel, "send"):
        try:
            await channel.send(content=message)
            await interaction.edit_original_response(content="✅ Sent!")
            return
        except Exception as e:
            logger.warning(f"channel.send failed in /say: {e}")

    # Fallback for uninvited User App mode: Send via followup
    try:
        await interaction.followup.send(content=message, ephemeral=False)
        await interaction.edit_original_response(content="✅ Sent!")
        try:
            await asyncio.sleep(2)
            await interaction.delete_original_response()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Failed to send /say: {e}")
        try:
            await interaction.edit_original_response(content=f"❌ Failed to send: {e}")
        except Exception:
            pass


# ==========================================
# SLASH COMMAND: /stop
# ==========================================
@bot.tree.command(name="stop", description="Stop all active repeater tasks in this channel/chat.")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def slash_stop(interaction: discord.Interaction):
    session_key = interaction.channel_id or interaction.user.id
    running_tasks = [t for t in list(active_tasks.get(session_key, set())) if not t.done()]

    if running_tasks:
        for t in running_tasks:
            t.cancel()
        active_tasks[session_key].clear()
        await interaction.response.send_message(f"🛑 Stopped **{len(running_tasks)}** active task(s)!")
    else:
        await interaction.response.send_message("ℹ️ No active repeating task is running in this channel/chat.", ephemeral=True)


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token or token.startswith("YOUR_DISCORD_BOT_TOKEN"):
        print("\n" + "=" * 60)
        print(" [!] DISCORD_TOKEN is missing or not configured!")
        print("     Please check the '.env' file in this folder.")
        print("=" * 60 + "\n")
        return

    logger.info("Starting Discord bot...")
    bot.run(token)


if __name__ == "__main__":
    main()
